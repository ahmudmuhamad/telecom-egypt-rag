from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config.settings import ROOT_DIR, settings
from src.ingestion.schemas import (
    KBManifest,
    KBRejectedRecord,
    KBSourceFileConfig,
    UnifiedKBRecord,
)


MALFORMED_JSON_KEY = "__malformed_json__"

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
    "add_on_name",
    "section_title",
    "title",
    "record_id",
    "doc_id",
)

COMMON_METADATA_FIELDS = (
    "language_pair_key",
    "alternate_language_url",
    "source_url",
    "final_url",
    "canonical_url",
    "detail_url",
    "listing_url",
    "quality_flags",
)

CATEGORY_METADATA_FIELDS = {
    "faq": (
        "question",
        "answer",
        "faq_number",
    ),
    "devices": (
        "product_name",
        "normalized_product_name",
        "brand",
        "manufacturer",
        "device_category",
        "price",
        "price_numeric",
        "currency",
        "specifications",
        "warranty",
        "model",
        "availability",
    ),
    "services": (
        "service_name",
        "normalized_service_name",
        "service_category",
        "service_category_display",
        "subscription_code",
        "ussd_codes",
        "sms_number",
        "sms_format",
        "fee",
        "fee_notes",
        "price",
        "price_numeric",
        "currency",
        "currency_subunit",
        "minimum_payment",
        "maximum_payment",
        "service_channel",
        "search_aliases",
        "terms_and_conditions",
        "requirements",
        "eligibility",
        "steps",
    ),
    "we_home": (
        "pillar",
        "product_family",
        "tier",
        "package_name",
        "normalized_package_name",
        "quota",
        "quota_gb",
        "quota_tb",
        "speed",
        "download_speed",
        "upload_speed",
        "monthly_fee",
        "monthly_fee_egp",
        "yearly_fee",
        "yearly_fee_egp",
        "price",
        "price_egp",
        "currency",
        "billing_cycle",
        "validity",
        "renewal_type",
        "price_includes_vat",
        "vat_note",
        "payment_channels",
        "search_aliases",
        "features",
        "benefits",
        "terms_and_conditions",
    ),
}

INDEX_METADATA_LABELS = {
    "question": "Question",
    "answer": "Answer",
    "faq_number": "FAQ number",
    "product_name": "Product",
    "normalized_product_name": "Normalized product",
    "brand": "Brand",
    "manufacturer": "Manufacturer",
    "device_category": "Device category",
    "model": "Model",
    "availability": "Availability",
    "specifications": "Specifications",
    "warranty": "Warranty",
    "service_name": "Service",
    "normalized_service_name": "Normalized service",
    "service_category": "Service category",
    "service_category_display": "Service category display",
    "subscription_code": "Code",
    "ussd_codes": "USSD codes",
    "sms_number": "SMS number",
    "sms_format": "SMS format",
    "fee": "Fee",
    "fee_notes": "Fee notes",
    "minimum_payment": "Minimum payment",
    "maximum_payment": "Maximum payment",
    "service_channel": "Service channel",
    "requirements": "Requirements",
    "eligibility": "Eligibility",
    "steps": "Steps",
    "pillar": "Pillar",
    "product_family": "Product family",
    "tier": "Tier",
    "package_name": "Package",
    "normalized_package_name": "Normalized package",
    "quota": "Quota",
    "quota_gb": "Quota GB",
    "quota_tb": "Quota TB",
    "speed": "Speed",
    "download_speed": "Download speed",
    "upload_speed": "Upload speed",
    "monthly_fee": "Monthly fee",
    "monthly_fee_egp": "Monthly fee",
    "yearly_fee": "Yearly fee",
    "yearly_fee_egp": "Yearly fee",
    "price": "Price",
    "price_numeric": "Price numeric",
    "price_egp": "Price",
    "currency": "Currency",
    "billing_cycle": "Billing cycle",
    "validity": "Validity",
    "renewal_type": "Renewal type",
    "price_includes_vat": "Price includes VAT",
    "vat_note": "VAT note",
    "payment_channels": "Payment channels",
    "search_aliases": "Aliases",
    "features": "Features",
    "benefits": "Benefits",
    "terms_and_conditions": "Terms and conditions",
}

EXCLUDED_METADATA_FIELDS = {
    "content",
    "index_text",
    "original_content",
    "v1_content",
    "raw_html_path",
    "original_quality_flags",
    "original_quality_score",
    "original_record_id",
    "post_processed_at",
    "post_processed_v2_at",
    "post_processed_v3_at",
    "last_scraped",
    "original_record",
    "original_v1_content",
    "original_answer",
    "original_question",
    "source_raw_html_path",
    "raw_source_html_path",
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
                records.append(
                    {
                        MALFORMED_JSON_KEY: True,
                        "line_number": line_number,
                        "error": str(exc),
                        "raw_line": line.rstrip("\n"),
                    }
                )
                continue
            if not isinstance(value, dict):
                records.append(
                    {
                        MALFORMED_JSON_KEY: True,
                        "line_number": line_number,
                        "error": "JSONL row is not an object",
                        "raw_line": line.rstrip("\n"),
                    }
                )
                continue
            records.append(value)
    return records


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    raw_lines = text.strip().splitlines()
    lines = [" ".join(line.strip().split()) for line in raw_lines]
    useful_lines = [line for line in lines if line]
    return "\n".join(useful_lines).strip()


def compact_text(value: Any) -> str:
    return " ".join(clean_text(value).split())


def first_non_empty(*values: Any) -> Any | None:
    for value in values:
        if value not in (None, "", [], {}):
            if isinstance(value, str) and not clean_text(value):
                continue
            return value
    return None


def stable_hash(text: str, length: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def value_from_raw_or_structured(raw: dict[str, Any], key: str) -> Any:
    value = raw.get(key)
    if value not in (None, "", [], {}):
        return value
    structured = raw.get("structured_data")
    if isinstance(structured, dict):
        value = structured.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def build_record_id(
    raw: dict[str, Any],
    category: str,
    title: str,
    content: str,
    citation_url: str,
) -> str:
    raw_record_id = compact_text(raw.get("record_id"))
    if raw_record_id:
        return raw_record_id

    doc_id = compact_text(raw.get("doc_id"))
    if doc_id:
        return f"{doc_id}:{stable_hash(content or citation_url)}"

    return stable_hash(f"{category}\n{title}\n{content}\n{citation_url}", length=64)


def resolve_citation_url(raw: dict[str, Any]) -> str | None:
    for field in CITATION_FIELDS:
        value = compact_text(raw.get(field))
        if value:
            return value
    return None


def build_title(raw: dict[str, Any]) -> str:
    for field in TITLE_FIELDS:
        value = compact_text(raw.get(field))
        if value:
            return value
    return "Untitled Record"


def resolve_category(raw: dict[str, Any], category_hint: str) -> str:
    category = compact_text(raw.get("category")) or compact_text(category_hint)
    normalized = category.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "faq": "faq",
        "faqs": "faq",
        "device": "devices",
        "devices": "devices",
        "service": "services",
        "services": "services",
        "we_home": "we_home",
        "home": "we_home",
    }
    return aliases.get(normalized, normalized)


def resolve_record_type(raw: dict[str, Any]) -> tuple[str, list[str]]:
    explicit = compact_text(raw.get("record_type"))
    if explicit:
        return explicit, []

    warnings = ["missing_record_type"]
    if first_non_empty(raw.get("question"), raw.get("answer")) and raw.get("question") and raw.get("answer"):
        return "faq", warnings
    if first_non_empty(raw.get("product_name")):
        return "product", warnings
    if first_non_empty(raw.get("service_name")):
        return "service_detail", warnings
    if first_non_empty(raw.get("package_name"), value_from_raw_or_structured(raw, "package_name")):
        if first_non_empty(raw.get("yearly_fee_egp"), value_from_raw_or_structured(raw, "yearly_fee_egp")):
            return "yearly_package", warnings
        return "package", warnings
    return "unknown", warnings


def remove_empty_values(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}


def build_metadata(raw: dict[str, Any], category: str) -> dict[str, Any]:
    fields = (*COMMON_METADATA_FIELDS, *CATEGORY_METADATA_FIELDS.get(category, ()))
    metadata: dict[str, Any] = {}
    for field in fields:
        if field in EXCLUDED_METADATA_FIELDS:
            continue
        value = value_from_raw_or_structured(raw, field)
        if value not in (None, "", [], {}):
            metadata[field] = value
    return remove_empty_values(metadata)


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
        return "\n".join(text for item in value if (text := value_to_index_text(item)))
    return clean_text(value)


def build_index_text(record: UnifiedKBRecord) -> str:
    parts = [
        f"Title: {record.title}",
        f"Category: {record.category}",
        f"Record type: {record.record_type}",
    ]
    if record.language:
        parts.append(f"Language: {record.language}")

    for key, label in INDEX_METADATA_LABELS.items():
        text = value_to_index_text(record.metadata.get(key))
        if text:
            parts.append(f"{label}: {text}")

    parts.append(f"Content:\n{record.content}")
    return "\n".join(part for part in parts if part).strip()


def normalize_record(
    raw: dict[str, Any],
    category_hint: str,
    source_file: str,
    kb_version: str,
) -> tuple[UnifiedKBRecord | None, KBRejectedRecord | None, list[str]]:
    if raw.get(MALFORMED_JSON_KEY):
        return (
            None,
            KBRejectedRecord(
                source_file=source_file,
                category=category_hint,
                raw_record_id=None,
                title=None,
                rejection_reason=f"malformed_json_line_{raw.get('line_number')}: {raw.get('error')}",
                raw_record=raw,
            ),
            [],
        )

    category = resolve_category(raw, category_hint)
    content = clean_text(raw.get("content"))
    citation_url = resolve_citation_url(raw)
    title = build_title(raw)
    raw_record_id = compact_text(raw.get("record_id")) or None

    rejection_reason = None
    if not content:
        rejection_reason = "empty_content"
    elif not citation_url:
        rejection_reason = "missing_citation_url"
    elif not category:
        rejection_reason = "missing_category"
    elif not title or title == "Untitled Record":
        rejection_reason = "missing_title"

    if rejection_reason:
        return (
            None,
            KBRejectedRecord(
                source_file=source_file,
                category=category or None,
                raw_record_id=raw_record_id,
                title=title if title else None,
                rejection_reason=rejection_reason,
                raw_record=raw,
            ),
            [],
        )

    record_type, warnings = resolve_record_type(raw)
    metadata = build_metadata(raw, category)
    if warnings:
        metadata["normalization_warnings"] = warnings

    quality_score = raw.get("quality_score")
    quality_score_value = float(quality_score) if quality_score is not None else None

    record = UnifiedKBRecord(
        record_id=build_record_id(raw, category, title, content, citation_url),
        kb_version=kb_version,
        source_type="official_website",
        source_name=compact_text(raw.get("source_name")) or "Telecom Egypt",
        category=category,
        record_type=record_type,
        language=compact_text(raw.get("language")) or None,
        title=title,
        content=content,
        index_text="",
        citation_url=citation_url,
        quality_score=quality_score_value,
        metadata=metadata,
        raw_source_file=source_file,
    )
    return record.model_copy(update={"index_text": build_index_text(record)}), None, warnings


def get_default_source_configs() -> list[KBSourceFileConfig]:
    return [
        KBSourceFileConfig(
            category="faq",
            path=Path("data/processed/faq/faq_post_processed.jsonl"),
            description="Official Telecom Egypt FAQ records.",
        ),
        KBSourceFileConfig(
            category="devices",
            path=Path("data/processed/devices/devices_post_processed_v2.jsonl"),
            description="Official Telecom Egypt device/product records.",
        ),
        KBSourceFileConfig(
            category="services",
            path=Path("data/processed/services/services_post_processed_v3.jsonl"),
            description="Official Telecom Egypt services records.",
        ),
        KBSourceFileConfig(
            category="we_home",
            path=Path("data/processed/we_home/we_home.jsonl"),
            description="Official Telecom Egypt WE Home records.",
        ),
        # Add a future category by appending one config:
        # KBSourceFileConfig(
        #     category="mobile",
        #     path=Path("data/processed/mobile/mobile_post_processed.jsonl"),
        # ),
    ]


def load_source_configs_from_yaml(path: Path) -> list[KBSourceFileConfig]:
    config_path = resolve_project_path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    sources = data.get("sources")
    if not isinstance(sources, list):
        raise ValueError(f"Expected 'sources' list in {config_path}.")

    configs: list[KBSourceFileConfig] = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError(f"Invalid source entry in {config_path}: {source!r}")
        configs.append(KBSourceFileConfig(**source))
    return configs


def get_source_configs(config_path: Path | None = None) -> list[KBSourceFileConfig]:
    yaml_path = config_path or Path("config/kb_sources.yaml")
    if resolve_project_path(yaml_path).exists():
        return load_source_configs_from_yaml(yaml_path)
    return get_default_source_configs()


def make_report_row(
    source_file: str,
    category: str,
    status: str,
    record: UnifiedKBRecord | None = None,
    rejected: KBRejectedRecord | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source_file": source_file,
        "category": category,
        "record_id": record.record_id if record else rejected.raw_record_id if rejected else "",
        "title": record.title if record else rejected.title if rejected else "",
        "record_type": record.record_type if record else "",
        "language": record.language if record and record.language else "",
        "citation_url": record.citation_url if record else "",
        "content_length": len(record.content) if record else 0,
        "index_text_length": len(record.index_text) if record else 0,
        "quality_score": record.quality_score if record and record.quality_score is not None else "",
        "status": status,
        "rejection_reason": rejected.rejection_reason if rejected else "",
        "warnings": ";".join(warnings or []),
    }


def build_unified_kb(source_configs: list[KBSourceFileConfig], kb_version: str) -> dict[str, Any]:
    accepted: list[UnifiedKBRecord] = []
    rejected: list[KBRejectedRecord] = []
    report_rows: list[dict[str, Any]] = []
    source_file_summaries: list[dict[str, Any]] = []
    stats = {
        "total_input_records": 0,
        "missing_citation_count": 0,
        "empty_content_count": 0,
        "unknown_record_type_count": 0,
    }

    for config in source_configs:
        if not config.enabled:
            source_file_summaries.append(
                {
                    "category": config.category,
                    "path": str(config.path),
                    "enabled": False,
                    "description": config.description,
                    "input_records": 0,
                    "accepted_records": 0,
                    "rejected_records": 0,
                }
            )
            continue

        raw_records = load_jsonl(resolve_project_path(config.path))
        stats["total_input_records"] += len(raw_records)
        source_accepted = 0
        source_rejected = 0

        for raw in raw_records:
            record, rejection, warnings = normalize_record(
                raw=raw,
                category_hint=config.category,
                source_file=str(config.path),
                kb_version=kb_version,
            )
            if record is not None:
                accepted.append(record)
                source_accepted += 1
                if record.record_type == "unknown":
                    stats["unknown_record_type_count"] += 1
                report_rows.append(
                    make_report_row(
                        str(config.path),
                        config.category,
                        "accepted",
                        record=record,
                        warnings=warnings,
                    )
                )
                continue

            rejected.append(rejection)
            source_rejected += 1
            if rejection.rejection_reason == "missing_citation_url":
                stats["missing_citation_count"] += 1
            if rejection.rejection_reason == "empty_content":
                stats["empty_content_count"] += 1
            report_rows.append(
                make_report_row(
                    str(config.path),
                    config.category,
                    "rejected",
                    rejected=rejection,
                    warnings=warnings,
                )
            )

        source_file_summaries.append(
            {
                "category": config.category,
                "path": str(config.path),
                "enabled": config.enabled,
                "description": config.description,
                "input_records": len(raw_records),
                "accepted_records": source_accepted,
                "rejected_records": source_rejected,
            }
        )

    by_category = Counter(record.category for record in accepted)
    by_language = Counter(record.language or "unknown" for record in accepted)
    by_record_type = Counter(record.record_type for record in accepted)
    manifest = KBManifest(
        kb_version=kb_version,
        created_at=datetime.now(timezone.utc).isoformat(),
        embedding_provider=settings.embedding_provider,
        embedding_model=settings.embedding_model,
        index_version=settings.index_version,
        source_files=source_file_summaries,
        total_input_records=stats["total_input_records"],
        total_accepted_records=len(accepted),
        total_rejected_records=len(rejected),
        accepted_by_category=dict(sorted(by_category.items())),
        accepted_by_language=dict(sorted(by_language.items())),
        accepted_by_record_type=dict(sorted(by_record_type.items())),
    )
    return {
        "accepted_records": accepted,
        "rejected_records": rejected,
        "report_rows": report_rows,
        "manifest": manifest,
        "summary": {
            **stats,
            "accepted_by_category": manifest.accepted_by_category,
            "accepted_by_language": manifest.accepted_by_language,
            "accepted_by_record_type": manifest.accepted_by_record_type,
            "total_accepted_records": len(accepted),
            "total_rejected_records": len(rejected),
        },
    }
