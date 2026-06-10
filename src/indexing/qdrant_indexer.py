from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qdrant_client import models

from config.settings import ROOT_DIR, settings
from src.services.ollama_client import OllamaClient
from src.services.qdrant_client import get_qdrant_client


PAYLOAD_INDEX_FIELDS = (
    "source_type",
    "category",
    "record_type",
    "language",
    "upload_session_id",
    "document_id",
    "file_name",
    "product_family",
    "service_category",
    "device_category",
    "tier",
    "kb_version",
)

REPORT_COLUMNS = [
    "chunk_id",
    "category",
    "record_type",
    "language",
    "title",
    "citation_url",
    "vector_size",
    "status",
    "error",
]


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def load_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    with resolve_project_path(path).open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def point_id_from_chunk_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def payload_from_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    metadata = chunk.get("metadata") or {}
    payload = {
        "chunk_id": chunk.get("chunk_id"),
        "parent_record_id": chunk.get("parent_record_id"),
        "kb_version": chunk.get("kb_version"),
        "source_type": chunk.get("source_type"),
        "source_name": chunk.get("source_name"),
        "category": chunk.get("category"),
        "record_type": chunk.get("record_type"),
        "language": chunk.get("language"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "index_text": chunk.get("index_text"),
        "citation_url": chunk.get("citation_url"),
        "citation_label": chunk.get("citation_label"),
        "document_id": chunk.get("document_id"),
        "upload_session_id": chunk.get("upload_session_id"),
        "file_name": chunk.get("file_name"),
        "file_type": chunk.get("file_type"),
        "page_number": chunk.get("page_number"),
        "chunk_index": chunk.get("chunk_index"),
        "total_chunks": chunk.get("total_chunks"),
        "metadata": metadata,
        "product_family": metadata.get("product_family"),
        "service_category": metadata.get("service_category"),
        "device_category": metadata.get("device_category"),
        "tier": metadata.get("tier"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def create_payload_indexes(client, collection_name: str) -> list[str]:
    warnings: list[str] = []
    for field in PAYLOAD_INDEX_FIELDS:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            warnings.append(f"{field}: {exc}")
    return warnings


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    output = resolve_project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def append_report(path: Path, rows: list[dict[str, Any]], write_header: bool = False) -> None:
    output = resolve_project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    output = resolve_project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, ensure_ascii=False, indent=2)
        file.write("\n")


class QdrantIndexer:
    def __init__(self, ollama_client: OllamaClient | None = None) -> None:
        self.client = get_qdrant_client()
        self.ollama = ollama_client or OllamaClient()

    def build_index(
        self,
        chunks_path: Path,
        manifest_path: Path,
        report_path: Path,
        recreate: bool = True,
        batch_size: int = 16,
    ) -> dict[str, Any]:
        chunks = load_chunks(chunks_path)
        if not chunks:
            raise RuntimeError(f"No chunks found in {chunks_path}.")

        test_embedding = self.ollama.embed(["Telecom Egypt indexing dimension check"])[0]
        vector_size = len(test_embedding)
        collection_name = settings.qdrant_collection

        if recreate:
            self.client.recreate_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
        else:
            exists = self.client.collection_exists(collection_name)
            if not exists:
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=vector_size,
                        distance=models.Distance.COSINE,
                    ),
                )

        payload_index_warnings = create_payload_indexes(self.client, collection_name)
        report_output = resolve_project_path(report_path)
        if recreate or not report_output.exists():
            write_report(report_path, [])
        indexed = 0
        skipped = 0

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            batch_rows: list[dict[str, Any]] = []
            try:
                if not recreate:
                    existing_ids = self._existing_point_ids(collection_name, batch)
                    batch_to_index = [
                        chunk
                        for chunk in batch
                        if point_id_from_chunk_id(chunk["chunk_id"]) not in existing_ids
                    ]
                    skipped_batch = [chunk for chunk in batch if chunk not in batch_to_index]
                    skipped += len(skipped_batch)
                    batch_rows.extend(
                        make_report_row(chunk, vector_size, "skipped_existing", "")
                        for chunk in skipped_batch
                    )
                else:
                    batch_to_index = batch

                if not batch_to_index:
                    append_report(report_path, batch_rows)
                    self._write_progress_manifest(
                        manifest_path,
                        collection_name,
                        chunks,
                        vector_size,
                        payload_index_warnings,
                    )
                    continue

                vectors = self.ollama.embed([chunk["index_text"] for chunk in batch_to_index])
                points = [
                    models.PointStruct(
                        id=point_id_from_chunk_id(chunk["chunk_id"]),
                        vector=vector,
                        payload=payload_from_chunk(chunk),
                    )
                    for chunk, vector in zip(batch_to_index, vectors, strict=True)
                ]
                self.client.upsert(collection_name=collection_name, points=points)
                indexed += len(batch_to_index)
                batch_rows.extend(
                    make_report_row(chunk, vector_size, "indexed", "") for chunk in batch_to_index
                )
                append_report(report_path, batch_rows)
                self._write_progress_manifest(
                    manifest_path,
                    collection_name,
                    chunks,
                    vector_size,
                    payload_index_warnings,
                )
            except Exception as exc:
                append_report(
                    report_path,
                    [make_report_row(chunk, vector_size, "failed", str(exc)) for chunk in batch],
                )
                raise

        manifest = self._manifest(
            collection_name,
            chunks,
            vector_size,
            payload_index_warnings,
        )
        manifest["chunks_indexed_this_run"] = indexed
        manifest["chunks_skipped_existing_this_run"] = skipped
        write_manifest(manifest_path, manifest)
        return manifest

    def upsert_chunks(
        self,
        chunks: list[dict[str, Any]],
        recreate: bool = False,
        batch_size: int = 16,
    ) -> dict[str, Any]:
        if not chunks:
            return {"collection_name": settings.qdrant_collection, "chunks_indexed_this_run": 0}

        test_embedding = self.ollama.embed(["Telecom Egypt upload indexing dimension check"])[0]
        vector_size = len(test_embedding)
        collection_name = settings.qdrant_collection
        self._ensure_collection(collection_name, vector_size, recreate=recreate)
        payload_index_warnings = create_payload_indexes(self.client, collection_name)

        indexed = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = self.ollama.embed([chunk["index_text"] for chunk in batch])
            points = [
                models.PointStruct(
                    id=point_id_from_chunk_id(chunk["chunk_id"]),
                    vector=vector,
                    payload=payload_from_chunk(chunk),
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            self.client.upsert(collection_name=collection_name, points=points)
            indexed += len(points)

        return {
            "collection_name": collection_name,
            "vector_size": vector_size,
            "chunks_indexed_this_run": indexed,
            "payload_index_warnings": payload_index_warnings,
        }

    def delete_upload_session(self, upload_session_id: str) -> bool:
        if not upload_session_id:
            return False
        collection_name = settings.qdrant_collection
        try:
            if not self.client.collection_exists(collection_name):
                return False
            self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="source_type",
                                match=models.MatchValue(value="user_upload"),
                            ),
                            models.FieldCondition(
                                key="upload_session_id",
                                match=models.MatchValue(value=upload_session_id),
                            ),
                        ]
                    )
                ),
            )
            return True
        except Exception:
            return False

    def _ensure_collection(self, collection_name: str, vector_size: int, recreate: bool = False) -> None:
        if recreate:
            self.client.recreate_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
            return
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
            )
            return
        collection = self.client.get_collection(collection_name)
        current_size = getattr(collection.config.params.vectors, "size", None)
        if current_size is not None and int(current_size) != vector_size:
            raise RuntimeError(
                f"Qdrant collection '{collection_name}' vector size is {current_size}, "
                f"but uploaded chunks embed to {vector_size}."
            )

    def _existing_point_ids(self, collection_name: str, chunks: list[dict[str, Any]]) -> set[str]:
        ids = [point_id_from_chunk_id(chunk["chunk_id"]) for chunk in chunks]
        try:
            points = self.client.retrieve(collection_name=collection_name, ids=ids, with_payload=False)
        except Exception:
            return set()
        return {str(point.id) for point in points}

    def _manifest(
        self,
        collection_name: str,
        chunks: list[dict[str, Any]],
        vector_size: int,
        payload_index_warnings: list[str],
    ) -> dict[str, Any]:
        try:
            total_chunks_indexed = self.client.count(collection_name=collection_name).count
        except Exception:
            total_chunks_indexed = 0
        return {
            "collection_name": collection_name,
            "kb_version": chunks[0].get("kb_version"),
            "index_version": settings.index_version,
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.ollama_embedding_model,
            "vector_size": vector_size,
            "distance": "Cosine",
            "total_chunks_indexed": total_chunks_indexed,
            "total_chunks_expected": len(chunks),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "payload_index_warnings": payload_index_warnings,
        }

    def _write_progress_manifest(
        self,
        manifest_path: Path,
        collection_name: str,
        chunks: list[dict[str, Any]],
        vector_size: int,
        payload_index_warnings: list[str],
    ) -> None:
        manifest = self._manifest(
            collection_name,
            chunks,
            vector_size,
            payload_index_warnings,
        )
        write_manifest(manifest_path, manifest)


def make_report_row(chunk: dict[str, Any], vector_size: int, status: str, error: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk.get("chunk_id"),
        "category": chunk.get("category"),
        "record_type": chunk.get("record_type"),
        "language": chunk.get("language") or "",
        "title": chunk.get("title"),
        "citation_url": chunk.get("citation_url"),
        "vector_size": vector_size,
        "status": status,
        "error": error,
    }
