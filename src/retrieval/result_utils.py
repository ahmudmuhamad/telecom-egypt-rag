from __future__ import annotations

from typing import Any


RESULT_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "parent_record_id",
    "title",
    "content",
    "index_text",
    "citation_url",
    "citation_label",
    "document_id",
    "upload_session_id",
    "file_name",
    "file_type",
    "page_number",
    "source_type",
    "source_name",
    "category",
    "record_type",
    "language",
    "metadata",
    "chunk_index",
    "total_chunks",
    "retriever",
    "score",
    "dense_score",
    "bm25_score",
    "rrf_score",
    "boost_score",
    "final_score",
    "rank",
)


def normalize_retrieval_result(
    payload: dict[str, Any] | None,
    *,
    retriever: str,
    score: float = 0.0,
    rank: int | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    metadata = payload.get("metadata") or {}
    result = {
        "chunk_id": payload.get("chunk_id") or "",
        "parent_record_id": payload.get("parent_record_id") or "",
        "title": payload.get("title") or "",
        "content": payload.get("content") or "",
        "index_text": payload.get("index_text") or "",
        "citation_url": payload.get("citation_url") or "",
        "citation_label": payload.get("citation_label") or metadata.get("citation_label"),
        "document_id": payload.get("document_id") or metadata.get("document_id"),
        "upload_session_id": payload.get("upload_session_id") or metadata.get("upload_session_id"),
        "file_name": payload.get("file_name") or metadata.get("file_name"),
        "file_type": payload.get("file_type") or metadata.get("file_type"),
        "page_number": payload.get("page_number") or metadata.get("page_number"),
        "source_type": payload.get("source_type") or "official_website",
        "source_name": payload.get("source_name") or "Telecom Egypt",
        "category": payload.get("category"),
        "record_type": payload.get("record_type"),
        "language": payload.get("language"),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "chunk_index": payload.get("chunk_index", 0),
        "total_chunks": payload.get("total_chunks", 1),
        "retriever": retriever,
        "score": float(score or 0.0),
        "dense_score": None,
        "bm25_score": None,
        "rrf_score": None,
        "boost_score": 0.0,
        "final_score": 0.0,
        "rank": rank,
    }
    if retriever == "dense":
        result["dense_score"] = result["score"]
    elif retriever == "bm25":
        result["bm25_score"] = result["score"]
    return result


def rerank_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for rank, result in enumerate(results, start=1):
        result["rank"] = rank
    return results
