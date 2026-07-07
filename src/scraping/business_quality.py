from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


QUALITY_COLUMNS = [
    "record_id",
    "title",
    "service_name",
    "plan_name",
    "business_category",
    "record_type",
    "citation_url",
    "is_accepted",
    "quality_score",
    "quality_flags",
    "rejection_reason",
    "has_price",
    "has_quota",
    "has_units",
    "has_minutes",
    "has_sms",
    "has_features",
    "has_terms",
    "content_length",
    "source_url",
    "raw_html_path",
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
                "service_name": record.get("service_name"),
                "plan_name": record.get("plan_name"),
                "business_category": record.get("business_category"),
                "record_type": record.get("record_type"),
                "citation_url": record.get("citation_url"),
                "is_accepted": record.get("is_accepted"),
                "quality_score": record.get("quality_score"),
                "quality_flags": ";".join(record.get("quality_flags") or []),
                "rejection_reason": record.get("rejection_reason", ""),
                "has_price": bool(record.get("price")) or record.get("price_egp") is not None,
                "has_quota": bool(record.get("quota"))
                or record.get("quota_mb") is not None
                or record.get("quota_gb") is not None,
                "has_units": record.get("units") is not None,
                "has_minutes": record.get("minutes") is not None,
                "has_sms": record.get("sms") is not None,
                "has_features": bool(record.get("features") or record.get("benefits")),
                "has_terms": bool(record.get("terms_and_conditions")),
                "content_length": len(record.get("content") or ""),
                "source_url": record.get("source_url"),
                "raw_html_path": record.get("raw_html_path"),
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
        "counts_by_business_category": dict(
            Counter(record.get("business_category") for record in records)
        ),
        "counts_by_record_type": dict(Counter(record.get("record_type") for record in records)),
        "top_quality_flags": dict(flags.most_common(30)),
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
        "missing_terms_count": sum(1 for record in records if not record.get("terms_and_conditions")),
        "number_of_pages_fetched": pages_fetched,
        "failed_urls": failed_urls,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    return summary

