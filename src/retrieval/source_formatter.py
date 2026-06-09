from __future__ import annotations

from typing import Any


def format_source(result: dict[str, Any], source_id: int) -> dict[str, Any]:
    title = result.get("title") or "Telecom Egypt source"
    return {
        "source_id": source_id,
        "title": title,
        "source_type": result.get("source_type") or "official_website",
        "source_name": result.get("source_name") or "Telecom Egypt",
        "citation_url": result.get("citation_url") or "",
        "citation_label": f"Telecom Egypt - {title}",
        "category": result.get("category"),
        "record_type": result.get("record_type"),
        "language": result.get("language"),
        "snippet": make_snippet(result.get("content") or result.get("index_text") or ""),
        "score": float(result.get("final_score") or result.get("score") or 0.0),
        "metadata": result.get("metadata") or {},
    }


def make_snippet(text: str, max_chars: int = 500) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def format_results_for_display(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [format_source(result, source_id=index) for index, result in enumerate(results, start=1)]


def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return format_results_for_display(retrieved_docs)
