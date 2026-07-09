from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scraping.section_parser import (
    detect_language,
    normalize_key,
    normalize_whitespace,
)


MIN_ACCEPTED_CONTENT_LENGTH = 80


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def unique_strings(values: Iterable[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_whitespace(value)
        key = normalize_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def clean_content(text: str | None) -> tuple[str, bool]:
    output: list[str] = []
    seen: set[str] = set()
    removed = False
    for raw in (text or "").splitlines():
        line = normalize_whitespace(raw)
        key = normalize_key(line.lstrip("-* "))
        if not key:
            removed = True
            continue
        if key in seen:
            removed = True
            continue
        seen.add(key)
        output.append(line)
    cleaned = "\n".join(output).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, removed


def ensure_base_schema(record: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "record_id": "",
        "doc_id": "",
        "category": None,
        "section": None,
        "record_type": "overview",
        "language": None,
        "customer_segment": "corporate",
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": None,
        "listing_url": None,
        "detail_url": None,
        "final_url": None,
        "canonical_url": None,
        "citation_url": None,
        "title": None,
        "normalized_title": None,
        "section_name": None,
        "topic": None,
        "description": None,
        "short_summary": None,
        "content": None,
        "index_text": None,
        "structured_data": {},
        "search_aliases": [],
        "report_links": [],
        "download_links": [],
        "certificate_links": [],
        "people": [],
        "dates": [],
        "features": [],
        "benefits": [],
        "terms_and_conditions": [],
        "contact_information": {},
        "raw_html_path": None,
        "last_scraped": None,
        "post_processed_at": None,
        "rag_usage": "answer_source",
        "is_accepted": True,
        "quality_score": 0.0,
        "quality_flags": [],
        "rejection_reason": "",
    }
    output = {**defaults, **record}
    output["structured_data"] = output.get("structured_data") or {}
    for field in (
        "search_aliases",
        "report_links",
        "download_links",
        "certificate_links",
        "people",
        "dates",
        "features",
        "benefits",
        "terms_and_conditions",
        "quality_flags",
    ):
        output[field] = output.get(field) or []
    output["contact_information"] = output.get("contact_information") or {}
    return output


def build_index_text(record: dict[str, Any]) -> str:
    link_text = " ".join(
        link.get("text", "")
        for field in ("report_links", "download_links", "certificate_links")
        for link in record.get(field) or []
    )
    people_text = " ".join(
        f"{person.get('name', '')} {person.get('title', '')}" for person in record.get("people") or []
    )
    parts = [
        record.get("title"),
        record.get("section_name"),
        record.get("topic"),
        record.get("record_type"),
        " ".join(record.get("search_aliases") or []),
        " ".join(record.get("dates") or []),
        people_text,
        link_text,
        record.get("content"),
    ]
    return "\n".join(str(part) for part in parts if part).strip()


def stable_ids(record: dict[str, Any]) -> None:
    doc_basis = "|".join(
        [
            str(record.get("section") or ""),
            str(record.get("canonical_url") or record.get("citation_url") or ""),
            str(record.get("topic") or ""),
        ]
    )
    doc_id = hashlib.sha256(doc_basis.encode("utf-8")).hexdigest()
    content_hash = hashlib.sha256((record.get("content") or "").encode("utf-8")).hexdigest()
    record["doc_id"] = record.get("doc_id") or doc_id
    record["record_id"] = hashlib.sha256(
        f"{record['doc_id']}|{record.get('record_type')}|{record.get('title')}|{content_hash}".encode(
            "utf-8"
        )
    ).hexdigest()


def score_record(record: dict[str, Any], ui_noise_removed: bool) -> tuple[float, list[str], str]:
    flags = list(record.get("quality_flags") or [])
    content = record.get("content") or ""
    score = 1.0
    reason = ""
    if ui_noise_removed:
        flags.append("ui_noise_removed")
    if not record.get("citation_url"):
        flags.append("missing_citation")
        score -= 0.35
        reason = "missing citation_url"
    if not record.get("title"):
        flags.append("missing_title")
        score -= 0.2
    if len(content) < MIN_ACCEPTED_CONTENT_LENGTH:
        flags.append("short_content")
        score -= 0.35
        reason = reason or "short content"
    if not record.get("language"):
        flags.append("language_missing")
        score -= 0.1
    elif record.get("language") == "ar":
        flags.append("arabic_detected")
    elif record.get("language") == "en":
        flags.append("english_detected")
    elif record.get("language") == "mixed":
        flags.append("mixed_language")
    if record.get("report_links"):
        flags.append("report_links_found")
    if record.get("download_links") or record.get("certificate_links"):
        flags.append("download_links_found")
    if record.get("certificate_links"):
        flags.append("certificate_links_found")
    if record.get("people"):
        flags.append("people_cards_found")
    if record.get("dates"):
        flags.append("timeline_found")
    if normalize_key(content) in {"", normalize_key(record.get("title"))}:
        flags.append("navigation_noise_detected")
        reason = reason or "navigation-only content"
        score -= 0.35
    accepted = score >= 0.45 and not reason
    if not accepted:
        flags.append("rejected_low_quality")
    return round(max(0.0, min(score, 1.0)), 2), unique_strings(flags), "" if accepted else reason


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = ensure_base_schema(record)
    normalized["title"] = normalize_whitespace(normalized.get("title"))
    normalized["normalized_title"] = normalize_key(normalized.get("title"))
    normalized["description"] = normalize_whitespace(normalized.get("description"))
    content, ui_noise_removed = clean_content(normalized.get("content"))
    normalized["content"] = content
    normalized["language"] = normalized.get("language") or detect_language(
        content, str(normalized.get("final_url") or "")
    )
    normalized["short_summary"] = normalized.get("description") or content[:240]
    normalized["search_aliases"] = unique_strings(
        [
            normalized.get("title"),
            normalized.get("section_name"),
            normalized.get("topic"),
            *(normalized.get("search_aliases") or []),
        ]
    )
    normalized["index_text"] = build_index_text(normalized)
    normalized["post_processed_at"] = utc_now_iso()
    normalized["rag_usage"] = "answer_source"
    stable_ids(normalized)
    score, flags, reason = score_record(normalized, ui_noise_removed)
    normalized["quality_score"] = score
    normalized["quality_flags"] = flags
    normalized["rejection_reason"] = reason
    normalized["is_accepted"] = not bool(reason)
    return normalized


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = "|".join(
            [
                str(record.get("section") or ""),
                str(record.get("record_type") or ""),
                str(record.get("citation_url") or ""),
                normalize_key(record.get("title")),
                hashlib.sha256((record.get("content") or "")[:1500].encode("utf-8")).hexdigest()[:12],
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def post_process_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_records([normalize_record(record) for record in records])


def post_process_jsonl(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    records = post_process_records(read_jsonl(input_path))
    write_jsonl(output_path, records)
    return records
