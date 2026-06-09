from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, settings
from src.ingestion.schemas import (
    KBBuildResult,
    KBManifest,
    KBRejectedRecord,
    KBSourceFileConfig,
    UnifiedKBRecord,
)


CITATION_FIELDS = (
    "citation_url",
    "canonical_url",
    "final_url",
    "detail_url",
    "source_url",
    "listing_url",
)

TITLE_FIELDS = (
    "question",
    "product_name",
    "service_name",
    "package_name",
    "section_title",
    "title",
    "record_id",
)

GENERAL_METADATA_FIELDS = (
    "doc_id",
    "source_url",
    "listing_url",
    "detail_url",
    "final_url",
    "canonical_url",
    "language_pair_key",
    "customer_segment",
    "currency",
    "quality_flags",
    "rag_usage",
    "is_accepted",
    "structured_data",
)

CATEGORY_METADATA_FIELDS = {
    "faq": (
        "question",
        "answer",
        "faq_number",
    ),
    "devices": (
        "product_name",
        "brand",
        "manufacturer",
        "device_category",
        "price",
        "price_numeric",
        "specifications",
        "warranty",
    ),
    "services": (
        "service_name",
        "service_category",
        "subscription_code",
        "ussd_codes",
        "fee",
        "price",
        "price_numeric",
        "service_channel",
        "search_aliases",
        "terms_and_conditions",
    ),
    "we_home": (
        "pillar",
        "product_family",
        "tier",
        "package_name",
        "quota",
        "quota_gb",
        "quota_tb",
        "speed",
        "download_speed",
        "upload_speed",
        "monthly_fee_egp",
        "yearly_fee_egp",
        "price_egp",
        "vat_note",
        "payment_channels",
        "search_aliases",
    ),
}

INDEX_METADATA_FIELDS = (
    "question",
    "answer",
    "faq_number",
    "product_name",
    "brand",
    "manufacturer",
    "device_category",
    "price",
    "price_numeric",
    "specifications",
    "warranty",
    "service_name",
    "service_category",
    "subscription_code",
    "ussd_codes",
    "fee",
    "service_channel",
    "terms_and_conditions",
    "pillar",
    "product_family",
    "tier",
    "package_name",
    "quota",
    "quota_gb",
    "quota_tb",
    "speed",
    "download_speed",
    "upload_speed",
    "monthly_fee_egp",
    "yearly_fee_egp",
    "price_egp",
    "vat_note",
    "payment_channels",
    "search_aliases",
)

EXCLUDED_METADATA_FIELDS = {
    "content",
    "index_text",
    "original_content",
    "original_answer",
    "original_question",
    "original_record",
    "original_v1_content",
    "v1_content",
    "raw_html_path",
}


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected object in {path} at line {line_number}.")
            records.append(value)
    return records


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.strip().split())
    return " ".join(str(value).strip().split())


def clean_multiline_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    lines = [" ".join(line.strip().split()) for line in text.strip().splitlines()]
    return "\n".join(line for line in lines if line).strip()


def get_first_text(raw: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = clean_text(raw.get(field))
        if value:
            return value
    return ""


def get_from_raw_or_structured(raw: dict[str, Any], field: str) -> Any:
    if field in raw and raw[field] not in (None, "", [], {}):
        return raw[field]
    structured = raw.get("structured_data")
    if isinstance(structured, dict) and structured.get(field) not in (None, "", [], {}):
        return structured[field]
    return None


def build_title(raw: dict[str, Any]) -> str:
    return get_first_text(raw, TITLE_FIELDS) or "Untitled official record"


def build_metadata(raw: dict[str, Any], category: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    fields = (*GENERAL_METADATA_FIELDS, *CATEGORY_METADATA_FIELDS.get(category, ()))

    for field in fields:
        if field in EXCLUDED_METADATA_FIELDS:
            continue
        value = get_from_raw_or_structured(raw, field)
        if value not in (None, "", [], {}):
            metadata[field] = value

    return metadata


def value_to_index_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = value_to_index_text(item)
            if text:
                parts.append(f"{key}: {text}")
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(value_to_index_text(item) for item in value if value_to_index_text(item))
    return clean_text(value)


def build_index_text(record: UnifiedKBRecord) -> str:
    parts = [
        f"Title: {record.title}",
        f"Category: {record.category}",
        f"Record type: {record.record_type}",
    ]
    if record.language:
        parts.append(f"Language: {record.language}")

    for field in INDEX_METADATA_FIELDS:
        text = value_to_index_text(record.metadata.get(field))
        if text:
            parts.append(f"{field}: {text}")

    parts.append(record.content)
    return "\n".join(part for part in parts if part).strip()


def make_stable_record_id(category: str, title: str, content: str, citation_url: str) -> str:
    source = f"{category}\n{title}\n{content}\n{citation_url}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def validate_record(raw: dict[str, Any], category: str, content: str, citation_url: str) -> tuple[bool, str, list[str]]:
    warnings: list[str] = []
    if not content:
        return False, "empty_content", warnings
    if not citation_url:
        return False, "missing_citation_url", warnings
    if not category:
        return False, "missing_category", warnings
    if not clean_text(raw.get("record_type")):
        warnings.append("missing_record_type")
    return True, "", warnings


def normalize_record(
    raw: dict[str, Any],
    category_hint: str,
    source_file: str,
) -> tuple[UnifiedKBRecord | None, dict[str, Any] | None]:
    category = clean_text(raw.get("category")) or category_hint
    content = clean_multiline_text(raw.get("content"))
    citation_url = get_first_text(raw, CITATION_FIELDS)
    is_valid, rejection_reason, warnings = validate_record(raw, category, content, citation_url)

    title = build_title(raw)
    record_id = clean_text(raw.get("record_id")) or make_stable_record_id(
        category=category,
        title=title,
        content=content,
        citation_url=citation_url,
    )

    if not is_valid:
        return None, {
            "source_file": source_file,
            "category": category or None,
            "record_id": record_id or None,
            "title": title,
            "rejection_reason": rejection_reason,
            "raw_record": raw,
        }

    record_type = clean_text(raw.get("record_type")) or "unknown"
    metadata = build_metadata(raw, category)
    if warnings:
        metadata["normalization_warnings"] = warnings

    quality_score = raw.get("quality_score")
    if quality_score is not None:
        quality_score = float(quality_score)

    record = UnifiedKBRecord(
        record_id=record_id,
        kb_version=settings.kb_version,
        source_type=clean_text(raw.get("source_type")) or "official_website",
        source_name=clean_text(raw.get("source_name")) or "Telecom Egypt",
        category=category,
        record_type=record_type,
        language=clean_text(raw.get("language")) or None,
        title=title,
        content=content,
        index_text="",
        citation_url=citation_url,
        quality_score=quality_score,
        metadata=metadata,
        raw_source_file=source_file,
    )
    return record.model_copy(update={"index_text": build_index_text(record)}), None


def make_report_row(
    source_file: str,
    category: str,
    status: str,
    record: UnifiedKBRecord | None = None,
    rejected: KBRejectedRecord | None = None,
) -> dict[str, Any]:
    return {
        "source_file": source_file,
        "category": category,
        "record_id": record.record_id if record else rejected.record_id if rejected else "",
        "title": record.title if record else rejected.title if rejected else "",
        "record_type": record.record_type if record else "",
        "language": record.language if record and record.language else "",
        "citation_url": record.citation_url if record else "",
        "content_length": len(record.content) if record else 0,
        "index_text_length": len(record.index_text) if record else 0,
        "quality_score": record.quality_score if record and record.quality_score is not None else "",
        "status": status,
        "rejection_reason": rejected.rejection_reason if rejected else "",
    }


def build_unified_kb(source_configs: list[KBSourceFileConfig]) -> KBBuildResult:
    accepted: list[UnifiedKBRecord] = []
    rejected: list[KBRejectedRecord] = []
    report_rows: list[dict[str, Any]] = []
    source_file_summaries: list[dict[str, Any]] = []
    total_input_records = 0
    missing_citation_count = 0
    empty_content_count = 0
    missing_record_type_count = 0

    for config in source_configs:
        path = resolve_project_path(config.path)
        raw_records = load_jsonl(path)
        total_input_records += len(raw_records)
        source_accepted = 0
        source_rejected = 0

        for raw in raw_records:
            record, rejection = normalize_record(
                raw=raw,
                category_hint=config.category,
                source_file=str(config.path),
            )
            if record is not None:
                accepted.append(record)
                source_accepted += 1
                if "missing_record_type" in record.metadata.get("normalization_warnings", []):
                    missing_record_type_count += 1
                report_rows.append(make_report_row(str(config.path), config.category, "accepted", record=record))
                continue

            rejected_record = KBRejectedRecord(**rejection)
            rejected.append(rejected_record)
            source_rejected += 1
            if rejected_record.rejection_reason == "missing_citation_url":
                missing_citation_count += 1
            if rejected_record.rejection_reason == "empty_content":
                empty_content_count += 1
            report_rows.append(
                make_report_row(
                    str(config.path),
                    config.category,
                    "rejected",
                    rejected=rejected_record,
                )
            )

        source_file_summaries.append(
            {
                "category": config.category,
                "path": str(config.path),
                "input_records": len(raw_records),
                "accepted_records": source_accepted,
                "rejected_records": source_rejected,
            }
        )

    by_category = Counter(record.category for record in accepted)
    by_language = Counter(record.language or "unknown" for record in accepted)
    by_record_type = Counter(record.record_type for record in accepted)

    manifest = KBManifest(
        kb_version=settings.kb_version,
        created_at=datetime.now(timezone.utc).isoformat(),
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        index_version=settings.index_version,
        source_files=source_file_summaries,
        total_input_records=total_input_records,
        total_accepted_records=len(accepted),
        total_rejected_records=len(rejected),
        accepted_by_category=dict(sorted(by_category.items())),
        accepted_by_language=dict(sorted(by_language.items())),
        accepted_by_record_type=dict(sorted(by_record_type.items())),
    )

    return KBBuildResult(
        records=accepted,
        rejected_records=rejected,
        manifest=manifest,
        report_rows=report_rows,
        missing_citation_count=missing_citation_count,
        empty_content_count=empty_content_count,
        missing_record_type_count=missing_record_type_count,
    )
