from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

from qdrant_client import models

from config.settings import ROOT_DIR, settings
from src.retrieval.result_utils import normalize_retrieval_result, rerank_results
from src.services.ollama_client import OllamaClient
from src.services.qdrant_client import get_qdrant_client

try:
    from src.services.metrics import (
        RAG_DENSE_RETRIEVAL_LATENCY,
        record_error,
        record_retrieval,
        track_latency,
    )
except Exception:  # pragma: no cover
    RAG_DENSE_RETRIEVAL_LATENCY = None
    record_error = None
    record_retrieval = None
    track_latency = None


FILTER_FIELDS = {
    "source_type",
    "category",
    "record_type",
    "language",
    "upload_session_id",
    "document_id",
    "file_name",
    "kb_version",
    "product_family",
    "service_category",
    "device_category",
    "tier",
}


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


class DenseRetriever:
    def __init__(
        self,
        collection_name: str | None = None,
        ollama_client: OllamaClient | None = None,
    ) -> None:
        self.collection_name = collection_name or settings.qdrant_collection
        self.client = get_qdrant_client()
        self.ollama = ollama_client or OllamaClient()

    def search(
        self,
        query: str,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        try:
            self._record_retrieval()
            if track_latency is None or RAG_DENSE_RETRIEVAL_LATENCY is None:
                return self._search(query, top_k=top_k, filters=filters)
            with track_latency(RAG_DENSE_RETRIEVAL_LATENCY):
                return self._search(query, top_k=top_k, filters=filters)
        except Exception:
            self._record_error()
            raise

    def _search(
        self,
        query: str,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_collection_exists()
        query_vector = self.ollama.embed([query])[0]
        query_filter = self.build_qdrant_filter(filters)
        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Dense Qdrant search failed for collection '{self.collection_name}': {exc}"
            ) from exc

        points = getattr(response, "points", response)
        results = [
            normalize_retrieval_result(
                getattr(point, "payload", {}) or {},
                retriever="dense",
                score=float(getattr(point, "score", 0.0) or 0.0),
                rank=rank,
            )
            for rank, point in enumerate(points, start=1)
        ]
        return rerank_results(results)

    def _record_retrieval(self) -> None:
        if record_retrieval is None:
            return
        try:
            record_retrieval("dense")
        except Exception:
            pass

    def _record_error(self) -> None:
        if record_error is None:
            return
        try:
            record_error("retrieval")
        except Exception:
            pass

    def build_qdrant_filter(self, filters: dict[str, Any] | None) -> models.Filter | None:
        if not filters:
            return None
        must: list[models.FieldCondition] = []
        for key, value in filters.items():
            if key not in FILTER_FIELDS or value in (None, "", []):
                continue
            values = value if isinstance(value, list) else [value]
            if len(values) == 1:
                must.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=values[0]))
                )
            else:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=values)))
        return models.Filter(must=must) if must else None

    def health_check(self) -> bool:
        self._ensure_collection_exists()
        try:
            self.client.get_collection(self.collection_name)
        except Exception as exc:
            raise RuntimeError(f"Qdrant is unreachable or unhealthy: {exc}") from exc

        try:
            self.ollama.embed(["Telecom Egypt retrieval health check"])
        except Exception as exc:
            raise RuntimeError(
                f"Ollama embedding model '{settings.ollama_embedding_model}' is unreachable: {exc}"
            ) from exc

        expected_chunks = self._count_chunks_file()
        if expected_chunks:
            try:
                indexed_count = self.client.count(collection_name=self.collection_name).count
            except Exception:
                indexed_count = 0
            if indexed_count < expected_chunks:
                warnings.warn(
                    f"Qdrant collection has {indexed_count} points but chunks file has "
                    f"{expected_chunks} rows.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        return True

    def _ensure_collection_exists(self) -> None:
        try:
            exists = self.client.collection_exists(self.collection_name)
        except Exception as exc:
            raise RuntimeError(f"Could not reach Qdrant at {settings.qdrant_url}: {exc}") from exc
        if not exists:
            raise RuntimeError(
                f"Qdrant collection '{self.collection_name}' does not exist. "
                "Build it with: uv run python scripts/build_qdrant_index.py"
            )

    def _count_chunks_file(self) -> int:
        chunks_path = resolve_project_path(
            settings.kb_dir / "telecom_egypt_kb_v1_chunks.jsonl"
        )
        if not chunks_path.exists():
            manifest_path = resolve_project_path(settings.index_dir / "qdrant_index_manifest_v1.json")
            if manifest_path.exists():
                try:
                    return int(json.loads(manifest_path.read_text(encoding="utf-8")).get("total_chunks_expected", 0))
                except Exception:
                    return 0
            return 0
        with chunks_path.open("r", encoding="utf-8") as file:
            return sum(1 for line in file if line.strip())
