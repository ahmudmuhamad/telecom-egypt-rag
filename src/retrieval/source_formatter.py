from __future__ import annotations

import re
from typing import Any

from config.settings import settings


def format_source(result: dict[str, Any], source_id: int) -> dict[str, Any]:
    title = result.get("title") or "Telecom Egypt source"
    content = result.get("content") or result.get("index_text") or ""
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
        "snippet": make_snippet(content),
        "content": content,
        "score": float(result.get("final_score") or result.get("score") or 0.0),
        "metadata": result.get("metadata") or {},
        "chunk_id": result.get("chunk_id"),
    }


def make_snippet(text: str, max_chars: int = 500) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max(0, max_chars - 3)].rstrip() + "..."


def format_results_for_display(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [format_source(result, source_id=index) for index, result in enumerate(results, start=1)]


def format_results_for_generation(
    results: list[dict[str, Any]],
    max_sources: int = 5,
    query: str = "",
) -> list[dict[str, Any]]:
    deduped = deduplicate_sources(results)
    sources: list[dict[str, Any]] = []
    for index, result in enumerate(deduped[:max_sources], start=1):
        source = format_source(result, source_id=index)
        source["content"] = compress_source_for_query(
            query,
            source,
            max_chars=settings.context_snippet_max_chars,
        )
        source["snippet"] = make_snippet(source["content"])
        sources.append(source)
    return sources


def compress_source_for_query(query: str, source: dict[str, Any], max_chars: int = 1200) -> str:
    content = source.get("content") or source.get("snippet") or ""
    header = "\n".join(
        part
        for part in (
            f"Title: {source.get('title') or ''}",
            f"Category: {source.get('category') or ''}",
            f"Record type: {source.get('record_type') or ''}",
        )
        if part.strip()
    )
    lines = [line.strip() for line in re.split(r"[\r\n]+", content) if line.strip()]
    keywords = _query_keywords(query)
    important_pattern = re.compile(
        r"(\*\d+[#*]?|#\d+\*?|\d[\d,]*(?:\.\d+)?|egp|le|gb|mbps|جنيه|قرش|قروش)",
        re.IGNORECASE,
    )
    selected: list[str] = []
    for line in lines:
        normalized = line.lower()
        if any(keyword in normalized for keyword in keywords) or important_pattern.search(line):
            selected.append(line)
    if not selected:
        selected = lines[:8]
    compressed = "\n".join([header, *selected]).strip()
    if len(compressed) <= max_chars:
        return compressed
    return compressed[: max(0, max_chars - 3)].rstrip() + "..."


def deduplicate_sources(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata") or {}
        content = result.get("content") or result.get("index_text") or ""
        package_or_product = (
            metadata.get("package_name")
            or metadata.get("service_name")
            or metadata.get("product_name")
            or result.get("title")
            or ""
        )
        price_quota = "|".join(
            str(metadata.get(key) or "")
            for key in (
                "price_numeric",
                "price_egp",
                "monthly_fee_egp",
                "yearly_fee_egp",
                "quota",
                "quota_gb",
                "speed",
            )
        )
        keys = [
            str(result.get("chunk_id") or ""),
            "|".join(
                [
                    str(result.get("citation_url") or ""),
                    str(result.get("title") or ""),
                    str(result.get("category") or ""),
                ]
            ),
            "|".join(
                [
                    str(result.get("citation_url") or ""),
                    str(result.get("title") or ""),
                    normalize_for_key(make_snippet(content, max_chars=180)),
                ]
            ),
            "|".join(
                [
                    str(result.get("record_type") or ""),
                    normalize_for_key(str(package_or_product)),
                    normalize_for_key(price_quota),
                ]
            ),
        ]
        active_keys = {candidate for candidate in keys if candidate.strip("|")}
        if active_keys & seen:
            continue
        seen.update(active_keys)
        deduped.append(result)
    return deduped


def normalize_for_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _query_keywords(query: str) -> list[str]:
    tokens = re.findall(r"\*?\#?\w[\w#*,-]*|[\u0600-\u06FF]+", (query or "").lower())
    stopwords = {"what", "is", "the", "for", "and", "are", "how", "can", "i", "a", "an"}
    return [token for token in tokens if len(token) > 1 and token not in stopwords]


def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return format_results_for_display(retrieved_docs)
