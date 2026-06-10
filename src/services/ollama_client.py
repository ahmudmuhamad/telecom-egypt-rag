from __future__ import annotations

import time
from typing import Any

import httpx

from config.settings import settings


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None, retries: int = 2) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.ollama_timeout_seconds
        self.retries = retries

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = httpx.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
        raise RuntimeError(f"Ollama request failed for {path}: {last_error}") from last_error

    def health_check(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not list Ollama models: {exc}") from exc

        return [model.get("name", "") for model in data.get("models", []) if model.get("name")]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.health_check():
            raise RuntimeError(f"Ollama is unreachable at {self.base_url}.")
        available = set(self.list_models())
        if settings.ollama_embedding_model not in available:
            raise RuntimeError(
                f"Ollama embedding model '{settings.ollama_embedding_model}' is not available. "
                "Pull it before indexing."
            )

        payload = {"model": settings.ollama_embedding_model, "input": texts}
        try:
            data = self._post("/api/embed", payload)
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and len(embeddings) == len(texts):
                return self._validate_embeddings(embeddings, len(texts))
        except RuntimeError as batch_error:
            fallback_reason = batch_error
        else:
            fallback_reason = RuntimeError("Ollama batch embedding response was invalid.")

        embeddings: list[list[float]] = []
        try:
            for text in texts:
                data = self._post(
                    "/api/embeddings",
                    {"model": settings.ollama_embedding_model, "prompt": text},
                )
                embedding = data.get("embedding")
                if not isinstance(embedding, list) or not embedding:
                    raise RuntimeError("Ollama embedding response did not contain a non-empty vector.")
                embeddings.append(embedding)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Ollama embedding failed. Batch endpoint error: {fallback_reason}; "
                f"single-input endpoint error: {exc}"
            ) from exc

        return self._validate_embeddings(embeddings, len(texts))

    def _validate_embeddings(
        self,
        embeddings: list[list[float]],
        expected_count: int,
    ) -> list[list[float]]:
        if len(embeddings) != expected_count:
            raise RuntimeError(
                f"Ollama returned {len(embeddings)} embeddings for {expected_count} texts."
            )
        dimensions = {len(embedding) for embedding in embeddings if isinstance(embedding, list)}
        if len(dimensions) != 1 or not dimensions or 0 in dimensions:
            raise RuntimeError(f"Ollama returned inconsistent embedding dimensions: {dimensions}")
        for embedding in embeddings:
            if not all(isinstance(value, int | float) for value in embedding):
                raise RuntimeError("Ollama returned a non-numeric embedding value.")
        return embeddings

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> str:
        selected_model = model or settings.default_generation_model
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            data = self._post(
                "/api/chat",
                {
                    "model": selected_model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": settings.ollama_generation_num_predict,
                    },
                },
            )
            content = data.get("message", {}).get("content")
        except RuntimeError as chat_error:
            prompt_parts = []
            if system:
                prompt_parts.append(f"System:\n{system}")
            prompt_parts.append(f"User:\n{prompt}")
            data = self._post(
                "/api/generate",
                {
                    "model": selected_model,
                    "prompt": "\n\n".join(prompt_parts),
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": settings.ollama_generation_num_predict,
                    },
                },
            )
            content = data.get("response")
            if not isinstance(content, str):
                raise chat_error
        if not isinstance(content, str):
            raise RuntimeError("Ollama chat response did not contain message.content.")
        return content.strip()

    def ensure_models_available(self, required_models: list[str]) -> dict[str, bool]:
        available = set(self.list_models())
        return {model: model in available for model in required_models}


if __name__ == "__main__":
    client = OllamaClient()
    required = [
        "qwen3-embedding:4b",
        "qwen3.5:0.8b",
        "qwen3.5:2b",
        "qwen3:4b",
    ]
    print("Ollama reachable:", client.health_check())
    print("Local models:", client.list_models() if client.health_check() else [])
    print("Required models:", client.ensure_models_available(required) if client.health_check() else {})
