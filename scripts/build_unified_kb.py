from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.ingestion.load_official_kb import build_unified_kb, resolve_project_path
from src.ingestion.schemas import KBSourceFileConfig


DEFAULT_SOURCE_CONFIGS = [
    KBSourceFileConfig(
        category="faq",
        path=Path("data/processed/faq/faq_post_processed.jsonl"),
    ),
    KBSourceFileConfig(
        category="devices",
        path=Path("data/processed/devices/devices_post_processed_v2.jsonl"),
    ),
    KBSourceFileConfig(
        category="services",
        path=Path("data/processed/services/services_post_processed_v3.jsonl"),
    ),
    KBSourceFileConfig(
        category="we_home",
        path=Path("data/processed/we_home/we_home.jsonl"),
    ),
    # Future categories can be added without changing the builder logic:
    # KBSourceFileConfig(
    #     category="mobile",
    #     path=Path("data/processed/mobile/mobile_post_processed.jsonl"),
    # ),
]

REPORT_COLUMNS = [
    "source_file",
    "category",
    "record_id",
    "title",
    "record_type",
    "language",
    "citation_url",
    "content_length",
    "index_text_length",
    "quality_score",
    "status",
    "rejection_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the unified official Telecom Egypt knowledge base JSONL."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/knowledge_base/telecom_egypt_kb_v1.jsonl"),
        help="Accepted unified KB JSONL output path.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/knowledge_base/kb_manifest_v1.json"),
        help="KB manifest JSON output path.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/knowledge_base/kb_build_report_v1.csv"),
        help="Build report CSV output path.",
    )
    parser.add_argument(
        "--rejected",
        type=Path,
        default=Path("data/knowledge_base/kb_rejected_records_v1.jsonl"),
        help="Rejected records JSONL output path.",
    )
    return parser.parse_args()


def to_dict(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(row, file, ensure_ascii=False, indent=2)
        file.write("\n")


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(
    result,
    output_path: Path,
    manifest_path: Path,
    report_path: Path,
    rejected_path: Path,
) -> None:
    manifest = result.manifest
    print("Unified KB build complete")
    print(f"Total input records: {manifest.total_input_records}")
    print(f"Accepted records: {manifest.total_accepted_records}")
    print(f"Rejected records: {manifest.total_rejected_records}")
    print(f"Accepted by category: {manifest.accepted_by_category}")
    print(f"Accepted by language: {manifest.accepted_by_language}")
    print(f"Accepted by record_type: {manifest.accepted_by_record_type}")
    print(f"Missing citation count: {result.missing_citation_count}")
    print(f"Empty content count: {result.empty_content_count}")
    print(f"Missing record_type warnings: {result.missing_record_type_count}")
    print(f"KB JSONL: {output_path}")
    print(f"Manifest JSON: {manifest_path}")
    print(f"Report CSV: {report_path}")
    print(f"Rejected JSONL: {rejected_path}")


def main() -> None:
    args = parse_args()
    settings.ensure_directories()

    output_path = resolve_project_path(args.output)
    manifest_path = resolve_project_path(args.manifest)
    report_path = resolve_project_path(args.report)
    rejected_path = resolve_project_path(args.rejected)

    result = build_unified_kb(DEFAULT_SOURCE_CONFIGS)

    write_jsonl(output_path, [to_dict(record) for record in result.records])
    write_jsonl(rejected_path, [to_dict(record) for record in result.rejected_records])
    write_json(manifest_path, to_dict(result.manifest))
    write_report(report_path, result.report_rows)

    print_summary(result, output_path, manifest_path, report_path, rejected_path)


if __name__ == "__main__":
    main()
