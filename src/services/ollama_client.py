from __future__ import annotations

from typing import Any

import httpx

from config.settings import settings


class OllamaClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed for {path}: {exc}") from exc

    def health_check(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=10.0)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not list Ollama models: {exc}") from exc

        return [model.get("name", "") for model in data.get("models", []) if model.get("name")]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {"model": settings.ollama_embedding_model, "input": texts}
        try:
            data = self._post("/api/embed", payload)
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and len(embeddings) == len(texts):
                return embeddings
        except RuntimeError:
            pass

        embeddings: list[list[float]] = []
        for text in texts:
            data = self._post(
                "/api/embeddings",
                {"model": settings.ollama_embedding_model, "prompt": text},
            )
            embedding = data.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                raise RuntimeError("Ollama embedding response did not contain a non-empty vector.")
            embeddings.append(embedding)

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

        data = self._post(
            "/api/chat",
            {
                "model": selected_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        content = data.get("message", {}).get("content")
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
