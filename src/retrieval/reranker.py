from __future__ import annotations

import warnings
from queue import Queue
from threading import Thread
from typing import Any

from config.settings import settings

try:
    import torch
except Exception:  # pragma: no cover
    torch = None

try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover
    CrossEncoder = None


class Reranker:
    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        max_length: int | None = None,
        batch_size: int | None = None,
        enabled: bool | None = None,
        strict_mode: bool | None = None,
        fallback_model_name: str | None = None,
    ) -> None:
        self.model_name = model_name or settings.reranker_model
        self.fallback_model_name = fallback_model_name or settings.reranker_fallback_model
        self.device_setting = device or settings.rerank_device
        self.max_length = max_length if max_length is not None else settings.rerank_max_length
        self.batch_size = batch_size if batch_size is not None else settings.rerank_batch_size
        self.enabled = settings.enable_reranking if enabled is None else enabled
        self.strict_mode = settings.rerank_strict_mode if strict_mode is None else strict_mode
        self.load_timeout_seconds = settings.rerank_load_timeout_seconds
        self.device = self.resolve_device()
        self.model: Any | None = None
        self.loaded_model_name: str | None = None
        self.last_error: str | None = None

    def is_enabled(self) -> bool:
        return bool(self.enabled)

    def resolve_device(self) -> str | None:
        requested = (self.device_setting or "auto").lower().strip()
        cuda_available = bool(torch is not None and torch.cuda.is_available())
        if requested == "auto":
            return "cuda" if cuda_available else "cpu"
        if requested == "cpu":
            return "cpu"
        if requested == "cuda":
            if cuda_available:
                return "cuda"
            message = "RERANK_DEVICE=cuda was requested but CUDA is not available."
            if self.strict_mode:
                raise RuntimeError(message)
            warnings.warn(f"{message} Falling back to CPU.", RuntimeWarning, stacklevel=2)
            return "cpu"
        return requested or None

    def load_model(self) -> None:
        if not self.is_enabled():
            return
        if self.model is not None:
            return
        if CrossEncoder is None:
            self._handle_load_failure(RuntimeError("sentence_transformers.CrossEncoder is unavailable."))
            return

        errors: list[str] = []
        for name in self._candidate_model_names():
            try:
                self.model = self._load_cross_encoder_with_timeout(name)
                self.loaded_model_name = name
                self.last_error = None
                return
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                warnings.warn(f"Could not load reranker model '{name}': {exc}", RuntimeWarning, stacklevel=2)

        self._handle_load_failure(RuntimeError("; ".join(errors)))

    def build_candidate_text(self, result: dict[str, Any]) -> str:
        metadata = result.get("metadata") or {}
        lines = [
            ("Title", result.get("title")),
            ("Category", result.get("category")),
            ("Record type", result.get("record_type")),
            ("Language", result.get("language")),
            ("Product family", metadata.get("product_family")),
            ("Tier", metadata.get("tier")),
            ("Package", metadata.get("package_name") or metadata.get("normalized_package_name")),
            ("Quota", metadata.get("quota") or metadata.get("quota_gb")),
            ("Speed", metadata.get("speed")),
            (
                "Price/Fee",
                metadata.get("price")
                or metadata.get("price_egp")
                or metadata.get("price_numeric")
                or metadata.get("monthly_fee")
                or metadata.get("monthly_fee_egp")
                or metadata.get("yearly_fee")
                or metadata.get("yearly_fee_egp")
                or metadata.get("fee"),
            ),
            ("Service", metadata.get("service_name") or result.get("title")),
            ("Code", metadata.get("subscription_code") or metadata.get("ussd_codes")),
            (
                "Brand/Product",
                metadata.get("brand") or metadata.get("product_name") or metadata.get("device_name"),
            ),
        ]
        text_parts = [f"{label}: {value}" for label, value in lines if value not in (None, "", [])]
        text_parts.append("Content:")
        text_parts.append(result.get("content") or result.get("index_text") or "")
        return "\n".join(text_parts)

    def score_pairs(self, query: str, candidate_texts: list[str]) -> list[float]:
        self.load_model()
        if self.model is None:
            raise RuntimeError(self.last_error or "Reranker model is not loaded.")
        pairs = [(query, candidate_text) for candidate_text in candidate_texts]
        scores = self.model.predict(pairs, batch_size=self.batch_size)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if not isinstance(scores, list):
            scores = list(scores)
        return [float(score) for score in scores]

    def rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        if not results:
            return []
        if not self.is_enabled():
            return self._with_disabled_fields(results, top_k=top_k)

        candidate_texts = [self.build_candidate_text(result) for result in results]
        try:
            scores = self.score_pairs(query, candidate_texts)
        except Exception as exc:
            self.last_error = str(exc)
            if self.strict_mode:
                raise
            warnings.warn(f"Reranking failed and will be skipped: {exc}", RuntimeWarning, stacklevel=2)
            self.enabled = False
            return self._with_disabled_fields(results, top_k=top_k)

        reranked: list[dict[str, Any]] = []
        for pre_rank, (result, score, candidate_text) in enumerate(
            zip(results, scores, candidate_texts, strict=True),
            start=1,
        ):
            item = dict(result)
            item["reranker_score"] = score
            item["pre_rerank_rank"] = result.get("rank", pre_rank)
            item["pre_rerank_score"] = result.get("final_score")
            item["final_score"] = score
            item["retriever"] = "hybrid_reranked"
            item["reranker_model"] = self.loaded_model_name or self.model_name
            item["reranker_text"] = candidate_text
            reranked.append(item)

        reranked.sort(key=lambda item: item["reranker_score"], reverse=True)
        if top_k is not None:
            reranked = reranked[:top_k]
        for rank, item in enumerate(reranked, start=1):
            item["rank"] = rank
        return reranked

    def health_check(self) -> bool:
        try:
            self.load_model()
            return self.model is not None
        except Exception:
            return False

    def _load_cross_encoder(self, model_name: str) -> Any:
        try:
            return CrossEncoder(model_name, device=self.device, max_length=self.max_length)
        except TypeError as exc:
            if "max_length" not in str(exc):
                raise
            warnings.warn(
                "Installed CrossEncoder does not accept max_length in the constructor; "
                "loading without it.",
                RuntimeWarning,
                stacklevel=2,
            )
            model = CrossEncoder(model_name, device=self.device)
            if hasattr(model, "max_length"):
                try:
                    model.max_length = self.max_length
                except Exception:
                    pass
            return model

    def _load_cross_encoder_with_timeout(self, model_name: str) -> Any:
        timeout = max(0, int(self.load_timeout_seconds or 0))
        if timeout == 0:
            return self._load_cross_encoder(model_name)

        queue: Queue[tuple[str, Any]] = Queue(maxsize=1)

        def load() -> None:
            try:
                queue.put(("ok", self._load_cross_encoder(model_name)))
            except Exception as exc:
                queue.put(("error", exc))

        thread = Thread(target=load, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError(
                f"Timed out after {timeout}s loading CrossEncoder model '{model_name}'. "
                "The model may still be downloading; reranking is skipped for this run."
            )

        status, payload = queue.get()
        if status == "error":
            raise payload
        return payload

    def _candidate_model_names(self) -> list[str]:
        names = [self.model_name]
        if self.fallback_model_name and self.fallback_model_name not in names:
            names.append(self.fallback_model_name)
        return names

    def _handle_load_failure(self, exc: Exception) -> None:
        self.last_error = str(exc)
        if self.strict_mode:
            raise exc
        warnings.warn(
            f"Reranker disabled because model loading failed: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        self.enabled = False

    def _with_disabled_fields(
        self,
        results: list[dict[str, Any]],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        selected = results[:top_k] if top_k is not None else results
        for rank, result in enumerate(selected, start=1):
            item = dict(result)
            item["rank"] = rank
            item.setdefault("reranker_score", None)
            item.setdefault("pre_rerank_rank", result.get("rank"))
            item.setdefault("pre_rerank_score", result.get("final_score"))
            item.setdefault("reranker_model", None)
            output.append(item)
        return output
