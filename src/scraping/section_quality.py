from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


QUALITY_COLUMNS = [
    "record_id",
    "title",
    "category",
    "section",
    "record_type",
    "language",
    "citation_url",
    "is_accepted",
    "quality_score",
    "quality_flags",
    "rejection_reason",
    "has_report_links",
    "has_download_links",
    "has_people",
    "has_dates",
    "has_contact_information",
    "content_length",
    "source_url",
    "raw_html_path",
]


def write_quality_report(
    records: list[dict[str, Any]],
    csv_path: Path,
    summary_path: Path,
    *,
    section: str,
    total_urls: int,
    pages_fetched: int,
    failed_urls: list[dict[str, Any]],
    started_at: str,
    completed_at: str,
    output_files: dict[str, str],
) -> dict[str, Any]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for record in records:
        rows.append(
            {
                "record_id": record.get("record_id"),
                "title": record.get("title"),
                "category": record.get("category"),
                "section": record.get("section"),
                "record_type": record.get("record_type"),
                "language": record.get("language"),
                "citation_url": record.get("citation_url"),
                "is_accepted": record.get("is_accepted"),
                "quality_score": record.get("quality_score"),
                "quality_flags": ";".join(record.get("quality_flags") or []),
                "rejection_reason": record.get("rejection_reason", ""),
                "has_report_links": bool(record.get("report_links")),
                "has_download_links": bool(
                    record.get("download_links") or record.get("certificate_links")
                ),
                "has_people": bool(record.get("people")),
                "has_dates": bool(record.get("dates")),
                "has_contact_information": bool(record.get("contact_information")),
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
        "section": section,
        "total_urls": total_urls,
        "fetched_urls": pages_fetched,
        "failed_urls": len(failed_urls),
        "total_records": len(records),
        "accepted_records": len(accepted),
        "rejected_records": len(records) - len(accepted),
        "counts_by_record_type": dict(Counter(record.get("record_type") for record in records)),
        "counts_by_language": dict(Counter(record.get("language") for record in records)),
        "top_quality_flags": dict(flags.most_common(30)),
        "missing_citation_count": sum(1 for record in records if not record.get("citation_url")),
        "short_content_count": sum(1 for record in records if len(record.get("content") or "") < 80),
        "download_links_count": sum(
            1
            for record in records
            if record.get("download_links")
            or record.get("report_links")
            or record.get("certificate_links")
        ),
        "average_quality_score": round(
            sum(float(record.get("quality_score") or 0.0) for record in records)
            / max(1, len(records)),
            3,
        ),
        "started_at": started_at,
        "completed_at": completed_at,
        "output_files": output_files,
        "failed_url_details": failed_urls,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")
    return summary
