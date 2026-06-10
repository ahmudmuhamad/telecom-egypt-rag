from __future__ import annotations

import re
from typing import Any

from config.settings import settings


def format_source(result: dict[str, Any], source_id: int) -> dict[str, Any]:
    source_type = result.get("source_type") or "official_website"
    title = result.get("title") or ("Uploaded document" if source_type == "user_upload" else "Telecom Egypt source")
    content = result.get("content") or result.get("index_text") or ""
    citation_label = result.get("citation_label")
    if source_type == "user_upload":
        citation_label = citation_label or _upload_citation_label(result)
        source_name = "Uploaded document"
        citation_url = ""
    else:
        source_name = result.get("source_name") or "Telecom Egypt"
        citation_url = result.get("citation_url") or ""
        citation_label = citation_label or f"Telecom Egypt - {title}"
    return {
        "source_id": source_id,
        "title": title,
        "source_type": source_type,
        "source_name": source_name,
        "citation_url": citation_url,
        "citation_label": citation_label,
        "category": result.get("category"),
        "record_type": result.get("record_type"),
        "language": result.get("language"),
        "snippet": make_snippet(content),
        "content": content,
        "score": float(result.get("final_score") or result.get("score") or 0.0),
        "metadata": result.get("metadata") or {},
        "chunk_id": result.get("chunk_id"),
        "document_id": result.get("document_id"),
        "file_name": result.get("file_name"),
        "page_number": result.get("page_number"),
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
    deduped = deduplicate_sources(prefer_language_sources(results, query))
    sources: list[dict[str, Any]] = []
    for index, result in enumerate(deduped[:max_sources], start=1):
        source = format_source(result, source_id=index)
        source["content"] = compress_source_for_query(
            query,
            source,
            max_chars=settings.context_snippet_max_chars,
        )
        source["snippet"] = make_snippet(clean_user_visible_text(source["content"]))
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
        if result.get("source_type") == "user_upload":
            keys = [
                str(result.get("chunk_id") or ""),
                "|".join(
                    [
                        str(result.get("document_id") or metadata.get("document_id") or ""),
                        str(result.get("page_number") or metadata.get("page_number") or ""),
                        normalize_for_key(make_snippet(content, max_chars=220)),
                    ]
                ),
            ]
            active_keys = {candidate for candidate in keys if candidate.strip("|")}
            if active_keys & seen:
                continue
            seen.update(active_keys)
            deduped.append(result)
            continue
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
        value_signature = "|".join(_extract_value_signature(content))
        code_signature = "|".join(_extract_codes(content))
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
                    str(result.get("category") or ""),
                    value_signature,
                ]
            )
            if value_signature
            else "",
            "|".join(
                [
                    str(result.get("citation_url") or ""),
                    str(result.get("category") or ""),
                    code_signature,
                ]
            )
            if code_signature
            else "",
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


def prefer_language_sources(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    preferred = _preferred_language(query)
    if preferred is None:
        return results
    return sorted(
        results,
        key=lambda result: 0 if str(result.get("language") or "").lower() == preferred else 1,
    )


def clean_user_visible_text(text: str) -> str:
    cleaned_lines: list[str] = []
    skip_prefixes = (
        "title:",
        "category:",
        "record type:",
        "language:",
        "source:",
        "content:",
        "metadata:",
        "source type:",
        "source_name:",
        "retriever:",
    )
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = raw_line.replace("\ufeff", "").strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"service_detail", "eligibility", "service_fee", "subscription_method"}:
            continue
        if any(lowered.startswith(prefix) for prefix in skip_prefixes):
            continue
        line = re.sub(r"^\*\s+(\*\d[^ ]*#?)", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)
    cleaned = " ".join(cleaned_lines)
    cleaned = re.sub(
        r"\b(?:Title|Category|Record type|Language|Source|Content|Metadata|Source type)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(service_detail|eligibility|service_fee|subscription_method)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


def normalize_for_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _query_keywords(query: str) -> list[str]:
    tokens = re.findall(r"\*?\#?\w[\w#*,-]*|[\u0600-\u06FF]+", (query or "").lower())
    stopwords = {"what", "is", "the", "for", "and", "are", "how", "can", "i", "a", "an"}
    return [token for token in tokens if len(token) > 1 and token not in stopwords]


def _preferred_language(query: str) -> str | None:
    if re.search(r"[\u0600-\u06FF]", query or ""):
        return "ar"
    if re.search(r"[A-Za-z]", query or ""):
        return "en"
    return None


def _extract_value_signature(text: str) -> list[str]:
    values = _extract_codes(text)
    values.extend(
        re.findall(
            r"\d[\d,]*(?:\.\d+)?\s*(?:egp|le|pt|gb|mbps|جنيه|قرش|قروش)",
            text or "",
            flags=re.IGNORECASE,
        )
    )
    return values


def _extract_codes(text: str) -> list[str]:
    codes = re.findall(r"\*\s*\d+(?:\s*\*\s*[\w\u0600-\u06FF]+)*\s*#?", text or "")
    normalized = {re.sub(r"\s+", "", code) for code in codes}
    normalized = {code for code in normalized if code.endswith("#")}
    return sorted(normalized)


def format_sources(retrieved_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return format_results_for_display(retrieved_docs)


def _upload_citation_label(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    file_name = result.get("file_name") or metadata.get("file_name") or result.get("title") or "uploaded file"
    page_number = result.get("page_number") or metadata.get("page_number")
    if page_number:
        return f"Uploaded document — {file_name}, page {page_number}"
    return f"Uploaded document — {file_name}"
