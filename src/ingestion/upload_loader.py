from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, settings
from src.indexing.bm25_indexer import build_bm25_artifact_from_chunks
from src.indexing.qdrant_indexer import QdrantIndexer
from src.ingestion.chunking import chunk_uploaded_document
from src.ingestion.docling_converter import DoclingConverter

try:
    from src.services.metrics import (
        RAG_UPLOAD_PROCESSING_LATENCY,
        record_error,
        record_upload,
        track_latency,
    )
except Exception:  # pragma: no cover
    RAG_UPLOAD_PROCESSING_LATENCY = None
    record_error = None
    record_upload = None
    track_latency = None


class UploadProcessor:
    def __init__(self, upload_session_id: str, app_settings: Any = settings) -> None:
        self.upload_session_id = upload_session_id
        self.settings = app_settings
        self.upload_root = self._resolve_path(Path(self.settings.upload_dir))
        self.converter = DoclingConverter()
        self.qdrant_indexer = QdrantIndexer()

    @property
    def original_dir(self) -> Path:
        return self.upload_root / "original" / self.upload_session_id

    @property
    def processed_dir(self) -> Path:
        return self.upload_root / "processed" / self.upload_session_id

    @property
    def chunks_dir(self) -> Path:
        return self.upload_root / "chunks" / self.upload_session_id

    @property
    def manifests_dir(self) -> Path:
        return self.upload_root / "manifests" / self.upload_session_id

    @property
    def indexes_dir(self) -> Path:
        return self.upload_root / "indexes" / self.upload_session_id

    @property
    def bm25_index_path(self) -> Path:
        return self.indexes_dir / "upload_bm25.pkl"

    def save_uploaded_file(self, uploaded_file: Any) -> Path:
        if not self.settings.enable_uploads:
            raise RuntimeError("Uploads are disabled.")

        file_name = self.sanitize_file_name(str(uploaded_file.name))
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        allowed = self.allowed_extensions()
        if extension not in allowed:
            raise RuntimeError(f"Unsupported file type: {extension or 'unknown'}")

        data = uploaded_file.getbuffer()
        max_bytes = int(self.settings.max_upload_size_mb) * 1024 * 1024
        if len(data) > max_bytes:
            raise RuntimeError(f"File is larger than {self.settings.max_upload_size_mb} MB.")

        self.original_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.original_dir / file_name
        with output_path.open("wb") as file:
            file.write(data)
        return output_path

    def process_file(self, file_path: Path) -> dict[str, Any]:
        if track_latency is not None and RAG_UPLOAD_PROCESSING_LATENCY is not None:
            with track_latency(RAG_UPLOAD_PROCESSING_LATENCY):
                return self._process_file(file_path)
        return self._process_file(file_path)

    def _process_file(self, file_path: Path) -> dict[str, Any]:
        file_path = Path(file_path)
        file_type = file_path.suffix.lower().lstrip(".") or "unknown"
        try:
            converted = self.converter.convert_file(file_path, upload_session_id=self.upload_session_id)
            if converted.get("error"):
                raise RuntimeError(str(converted["error"]))
            if not (converted.get("text") or converted.get("markdown") or converted.get("pages")):
                raise RuntimeError("No readable text was extracted from the uploaded file.")

            processed_paths = self.converter.write_processed_outputs(converted, self.processed_dir)
            chunks = self.chunk_converted_document(converted)
            if not chunks:
                raise RuntimeError("No chunks were created from the uploaded file.")

            chunks_path = self.write_chunks(converted["document_id"], chunks)
            all_session_chunks = self.load_session_upload_chunks(self.upload_session_id)
            bm25_manifest = self.build_upload_bm25_index(all_session_chunks)
            qdrant_status = self.upsert_upload_chunks_to_qdrant(chunks)
            manifest = {
                "document_id": converted["document_id"],
                "upload_session_id": self.upload_session_id,
                "file_name": converted["file_name"],
                "file_type": converted["file_type"],
                "title": converted.get("title"),
                "chunks_count": len(chunks),
                "chunks_path": str(chunks_path),
                "bm25_index_path": str(self.bm25_index_path),
                "processed_paths": processed_paths,
                "bm25_manifest": bm25_manifest,
                "qdrant_status": qdrant_status,
            }
            self.write_manifest(converted["document_id"], manifest)
            self._record_upload(file_type, "success", len(chunks))
            return manifest
        except Exception:
            self._record_upload(file_type, "failed", 0)
            self._record_error("upload_processing")
            raise

    def chunk_converted_document(self, converted: dict[str, Any]) -> list[dict[str, Any]]:
        return chunk_uploaded_document(
            converted,
            upload_session_id=self.upload_session_id,
            chunk_size=int(self.settings.upload_chunk_size),
            chunk_overlap=int(self.settings.upload_chunk_overlap),
        )

    def build_upload_bm25_index(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.settings.upload_bm25_enabled:
            return {"enabled": False, "total_chunks": len(chunks)}
        self.indexes_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.manifests_dir / "upload_bm25_manifest.json"
        return build_bm25_artifact_from_chunks(chunks, self.bm25_index_path, manifest_path)

    def upsert_upload_chunks_to_qdrant(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.settings.upload_dense_enabled:
            return {"enabled": False, "chunks_indexed_this_run": 0}
        return self.qdrant_indexer.upsert_chunks(chunks, recreate=False)

    def load_session_upload_chunks(self, upload_session_id: str | None = None) -> list[dict[str, Any]]:
        session_id = upload_session_id or self.upload_session_id
        chunks_dir = self.upload_root / "chunks" / session_id
        if not chunks_dir.exists():
            return []
        chunks: list[dict[str, Any]] = []
        for path in sorted(chunks_dir.glob("*_chunks.jsonl")):
            with path.open("r", encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        chunks.append(json.loads(line))
        return chunks

    def load_session_upload_bm25(self, upload_session_id: str | None = None) -> Path | None:
        session_id = upload_session_id or self.upload_session_id
        path = self.upload_root / "indexes" / session_id / "upload_bm25.pkl"
        return path if path.exists() else None

    def clear_session_uploads(self, upload_session_id: str | None = None) -> None:
        session_id = upload_session_id or self.upload_session_id
        self.qdrant_indexer.delete_upload_session(session_id)
        for folder in ("original", "processed", "chunks", "manifests", "indexes"):
            path = self.upload_root / folder / session_id
            if path.exists():
                shutil.rmtree(path)

    def write_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> Path:
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        path = self.chunks_dir / f"{document_id}_chunks.jsonl"
        with path.open("w", encoding="utf-8") as file:
            for chunk in chunks:
                file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        return path

    def write_manifest(self, document_id: str, manifest: dict[str, Any]) -> Path:
        self.manifests_dir.mkdir(parents=True, exist_ok=True)
        path = self.manifests_dir / f"{document_id}_manifest.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(manifest, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return path

    def allowed_extensions(self) -> set[str]:
        configured = str(self.settings.upload_allowed_extensions or "")
        return {item.strip().lower().lstrip(".") for item in configured.split(",") if item.strip()}

    def sanitize_file_name(self, file_name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file_name).name).strip("._")
        return safe or "uploaded_file"

    def _resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path

    def _record_upload(self, file_type: str, status: str, chunks_count: int) -> None:
        if record_upload is None:
            return
        try:
            record_upload(file_type=file_type, status=status, chunks_count=chunks_count)
        except Exception:
            pass

    def _record_error(self, stage: str) -> None:
        if record_error is None:
            return
        try:
            record_error(stage)
        except Exception:
            pass


def load_uploaded_file(file_path: str) -> str:
    return Path(file_path).read_text(encoding="utf-8", errors="replace")

