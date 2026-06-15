from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


QUALITY_COLUMNS = [
    "record_id",
    "title",
    "language",
    "mobile_category",
    "record_type",
    "citation_url",
    "is_accepted",
    "quality_score",
    "quality_flags",
    "rejection_reason",
    "has_price",
    "has_quota",
    "has_code",
    "has_terms",
    "has_benefits",
    "content_length",
]
CLEANUP_COLUMNS = [
    "record_id",
    "title",
    "language",
    "mobile_category",
    "record_type",
    "citation_url",
    "is_accepted",
    "old_quality_score",
    "new_quality_score",
    "quality_flags",
    "content_length_before",
    "content_length_after",
    "ui_noise_removed",
    "code_before",
    "code_after",
    "quota_before",
    "quota_after",
    "kix_units",
    "has_price",
    "has_code",
    "has_kix_units",
    "has_quota",
    "possible_issue",
]


def write_quality_report(
    records: list[dict[str, Any]],
    csv_path: Path,
    summary_path: Path,
    *,
    pages_fetched: int,
    failed_urls: list[dict[str, Any]],
) -> dict[str, Any]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        rows.append(
            {
                "record_id": record.get("record_id"),
                "title": record.get("title"),
                "language": record.get("language"),
                "mobile_category": record.get("mobile_category"),
                "record_type": record.get("record_type"),
                "citation_url": record.get("citation_url"),
                "is_accepted": record.get("is_accepted"),
                "quality_score": record.get("quality_score"),
                "quality_flags": ";".join(record.get("quality_flags") or []),
                "rejection_reason": record.get("rejection_reason", ""),
                "has_price": record.get("price_egp") is not None
                or bool(record.get("price"))
                or record.get("monthly_fee_egp") is not None,
                "has_quota": record.get("quota_mb") is not None
                or record.get("quota_gb") is not None
                or bool(record.get("quota")),
                "has_code": bool(record.get("ussd_codes") or record.get("dial_code")),
                "has_terms": bool(record.get("terms_and_conditions")),
                "has_benefits": bool(record.get("benefits") or record.get("features")),
                "content_length": len(record.get("content") or ""),
            }
        )
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=QUALITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    accepted = [record for record in records if record.get("is_accepted")]
    flags = Counter(flag for record in records for flag in record.get("quality_flags") or [])
    summary = {
        "total_records": len(records),
        "accepted_records": len(accepted),
        "rejected_records": len(records) - len(accepted),
        "counts_by_language": dict(Counter(record.get("language") for record in records)),
        "counts_by_mobile_category": dict(
            Counter(record.get("mobile_category") for record in records)
        ),
        "counts_by_record_type": dict(Counter(record.get("record_type") for record in records)),
        "top_quality_flags": dict(flags.most_common(20)),
        "missing_price_count": sum(
            1 for record in records if not record.get("price") and record.get("price_egp") is None
        ),
        "missing_quota_count": sum(
            1
            for record in records
            if not record.get("quota")
            and record.get("quota_mb") is None
            and record.get("quota_gb") is None
        ),
        "missing_code_count": sum(1 for record in records if not record.get("ussd_codes")),
        "number_of_pages_fetched": pages_fetched,
        "failed_urls": failed_urls,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    return summary


def write_cleanup_report(
    records: list[dict[str, Any]],
    csv_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        flags = record.get("quality_flags") or []
        original_structured_data = record.get("original_structured_data") or {}
        rows.append(
            {
                "record_id": record.get("record_id"),
                "title": record.get("title"),
                "language": record.get("language"),
                "mobile_category": record.get("mobile_category"),
                "record_type": record.get("record_type"),
                "citation_url": record.get("citation_url"),
                "is_accepted": record.get("is_accepted"),
                "old_quality_score": record.get("original_quality_score"),
                "new_quality_score": record.get("quality_score"),
                "quality_flags": ";".join(flags),
                "content_length_before": len(record.get("original_content") or ""),
                "content_length_after": len(record.get("content") or ""),
                "ui_noise_removed": "ui_noise_removed" in flags,
                "code_before": ",".join(original_structured_data.get("ussd_codes") or []),
                "code_after": ",".join(record.get("ussd_codes") or []),
                "quota_before": original_structured_data.get("quota"),
                "quota_after": record.get("quota"),
                "kix_units": (record.get("structured_data") or {}).get("kix_units"),
                "has_price": record.get("price_egp") is not None
                or record.get("monthly_fee_egp") is not None
                or bool(record.get("price")),
                "has_code": bool(record.get("ussd_codes") or record.get("subscription_code")),
                "has_kix_units": bool((record.get("structured_data") or {}).get("kix_units")),
                "has_quota": bool(record.get("quota"))
                or record.get("quota_mb") is not None
                or record.get("quota_gb") is not None,
                "possible_issue": record.get("possible_issue", ""),
            }
        )
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CLEANUP_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    accepted = [record for record in records if record.get("is_accepted")]
    flags = Counter(flag for record in records for flag in record.get("quality_flags") or [])
    summary = {
        "total_records": len(records),
        "cleaned_records": len(records),
        "accepted_records": len(accepted),
        "rejected_records": len(records) - len(accepted),
        "ui_noise_removed_count": sum(
            1 for record in records if "ui_noise_removed" in (record.get("quality_flags") or [])
        ),
        "partial_code_replaced_count": sum(
            1 for record in records if "partial_code_replaced" in (record.get("quality_flags") or [])
        ),
        "kix_units_extracted_count": sum(
            1 for record in records if "kix_units_extracted" in (record.get("quality_flags") or [])
        ),
        "quota_from_consumption_rule_removed_count": sum(
            1
            for record in records
            if "quota_from_consumption_rule_removed" in (record.get("quality_flags") or [])
        ),
        "possible_issue_count": sum(1 for record in records if record.get("possible_issue")),
        "counts_by_language": dict(Counter(record.get("language") for record in records)),
        "counts_by_mobile_category": dict(
            Counter(record.get("mobile_category") for record in records)
        ),
        "counts_by_record_type": dict(Counter(record.get("record_type") for record in records)),
        "top_quality_flags": dict(flags.most_common(30)),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    return summary
