from __future__ import annotations

import json
import pickle
import warnings
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, settings
from src.indexing.bm25_indexer import TOKENIZER_VERSION, tokenize_for_bm25
from src.retrieval.dense_retriever import FILTER_FIELDS
from src.retrieval.result_utils import normalize_retrieval_result, rerank_results

try:
    from src.services.metrics import (
        RAG_BM25_RETRIEVAL_LATENCY,
        record_error,
        record_retrieval,
        track_latency,
    )
except Exception:  # pragma: no cover
    RAG_BM25_RETRIEVAL_LATENCY = None
    record_error = None
    record_retrieval = None
    track_latency = None


DEFAULT_BM25_PATH = Path("data/indexes/bm25_official_kb_v1.pkl")
DEFAULT_MANIFEST_PATH = Path("data/indexes/bm25_manifest_v1.json")
DEFAULT_CHUNKS_PATH = Path("data/knowledge_base/telecom_egypt_kb_v1_chunks.jsonl")


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


class BM25Retriever:
    def __init__(
        self,
        index_path: Path | str | None = None,
        chunks_path: Path | str | None = None,
        manifest_path: Path | str | None = None,
    ) -> None:
        self.index_path = resolve_project_path(Path(index_path or DEFAULT_BM25_PATH))
        self.manifest_path = resolve_project_path(Path(manifest_path or DEFAULT_MANIFEST_PATH))
        self.artifact = self._load_artifact(required=True)
        artifact_chunks_path = self.artifact.get("source_chunks_file") if isinstance(self.artifact, dict) else None
        self.chunks_path = resolve_project_path(
            Path(chunks_path or artifact_chunks_path or DEFAULT_CHUNKS_PATH)
        )
        self.bm25 = self.artifact["bm25"]
        self.chunk_refs = self.artifact.get("chunks") or []
        self.full_chunks_by_id = self._load_full_chunks()
        self._validate_manifest()

    def search(
        self,
        query: str,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            self._record_retrieval()
            if track_latency is None or RAG_BM25_RETRIEVAL_LATENCY is None:
                return self._search(query, top_k=top_k, filters=filters)
            with track_latency(RAG_BM25_RETRIEVAL_LATENCY):
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
        tokens = self.tokenize(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        candidates: list[tuple[int, float]] = []
        for index, score in enumerate(scores):
            if index >= len(self.chunk_refs):
                continue
            chunk = self._chunk_at(index)
            if self.metadata_matches(chunk, filters):
                candidates.append((index, float(score)))

        candidates.sort(key=lambda item: item[1], reverse=True)
        results: list[dict[str, Any]] = []
        for rank, (index, score) in enumerate(candidates[:top_k], start=1):
            results.append(
                normalize_retrieval_result(
                    self._chunk_at(index),
                    retriever="bm25",
                    score=score,
                    rank=rank,
                )
            )
        return rerank_results(results)

    def _record_retrieval(self) -> None:
        if record_retrieval is None:
            return
        try:
            record_retrieval("bm25")
        except Exception:
            pass

    def _record_error(self) -> None:
        if record_error is None:
            return
        try:
            record_error("retrieval")
        except Exception:
            pass

    def tokenize(self, text: str) -> list[str]:
        return tokenize_for_bm25(text)

    def metadata_matches(
        self,
        chunk_or_payload: dict[str, Any],
        filters: dict[str, Any] | None,
    ) -> bool:
        if not filters:
            return True
        metadata = chunk_or_payload.get("metadata") or {}
        for key, expected in filters.items():
            if key not in FILTER_FIELDS or expected in (None, "", []):
                continue
            actual = chunk_or_payload.get(key)
            if actual is None and isinstance(metadata, dict):
                actual = metadata.get(key)
            expected_values = expected if isinstance(expected, list) else [expected]
            if str(actual) not in {str(value) for value in expected_values}:
                return False
        return True

    def _load_artifact(self, required: bool = True) -> dict[str, Any]:
        if not self.index_path.exists():
            if not required:
                return {"bm25": None, "chunks": []}
            raise RuntimeError(
                f"BM25 index not found at {self.index_path}. "
                "Build it with: uv run python scripts/build_bm25_index.py"
            )
        with self.index_path.open("rb") as file:
            artifact = pickle.load(file)
        if not isinstance(artifact, dict) or "bm25" not in artifact:
            raise RuntimeError(f"Unsupported BM25 pickle shape at {self.index_path}.")
        if "chunks" not in artifact:
            raise RuntimeError(f"BM25 pickle at {self.index_path} does not include chunk refs.")
        return artifact

    def _load_full_chunks(self) -> dict[str, dict[str, Any]]:
        if not self.chunks_path.exists():
            warnings.warn(
                f"Chunks file {self.chunks_path} is missing; BM25 will use pickle refs only.",
                RuntimeWarning,
                stacklevel=2,
            )
            return {}
        chunks: dict[str, dict[str, Any]] = {}
        with self.chunks_path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                chunk_id = chunk.get("chunk_id")
                if chunk_id:
                    chunks[chunk_id] = chunk
        return chunks

    def _chunk_at(self, index: int) -> dict[str, Any]:
        ref = self.chunk_refs[index] or {}
        chunk_id = ref.get("chunk_id")
        if chunk_id and chunk_id in self.full_chunks_by_id:
            merged = dict(ref)
            merged.update(self.full_chunks_by_id[chunk_id])
            return merged
        return ref

    def _validate_manifest(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.warn(f"Could not read BM25 manifest {self.manifest_path}: {exc}")
            return
        manifest_total = manifest.get("total_chunks")
        if manifest_total is not None and int(manifest_total) != len(self.chunk_refs):
            warnings.warn(
                f"BM25 manifest has {manifest_total} chunks but pickle has {len(self.chunk_refs)}.",
                RuntimeWarning,
                stacklevel=2,
            )
        if manifest.get("tokenizer_version") and manifest["tokenizer_version"] != TOKENIZER_VERSION:
            warnings.warn(
                f"BM25 manifest tokenizer is {manifest['tokenizer_version']} but code is "
                f"{TOKENIZER_VERSION}.",
                RuntimeWarning,
                stacklevel=2,
            )


class UploadedBM25Retriever(BM25Retriever):
    def __init__(self, upload_session_id: str) -> None:
        self.upload_session_id = upload_session_id
        upload_root = resolve_project_path(settings.upload_dir)
        index_path = upload_root / "indexes" / upload_session_id / "upload_bm25.pkl"
        self.index_path = index_path
        self.manifest_path = upload_root / "manifests" / upload_session_id / "upload_bm25_manifest.json"
        self.artifact = self._load_artifact(required=False)
        self.chunks_path = upload_root / "chunks" / upload_session_id
        self.bm25 = self.artifact.get("bm25")
        self.chunk_refs = self.artifact.get("chunks") or []
        self.full_chunks_by_id = self._load_full_chunks()

    def search(
        self,
        query: str,
        top_k: int = 30,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.bm25 is None or not self.chunk_refs:
            return []
        filters = dict(filters or {})
        filters.setdefault("source_type", "user_upload")
        filters.setdefault("upload_session_id", self.upload_session_id)
        return super().search(query, top_k=top_k, filters=filters)

    def _load_full_chunks(self) -> dict[str, dict[str, Any]]:
        if not self.chunks_path.exists():
            return {}
        chunks: dict[str, dict[str, Any]] = {}
        for path in sorted(self.chunks_path.glob("*_chunks.jsonl")):
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    chunk_id = chunk.get("chunk_id")
                    if chunk_id:
                        chunks[chunk_id] = chunk
        return chunks

    def _validate_manifest(self) -> None:
        return
