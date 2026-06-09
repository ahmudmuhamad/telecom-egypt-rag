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

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None

from config.settings import settings
from src.ingestion.load_official_kb import (
    build_unified_kb,
    get_default_source_configs,
    resolve_project_path,
)


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
    "warnings",
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
    parser.add_argument(
        "--kb-version",
        default=settings.kb_version,
        help="Knowledge base version to stamp into records and manifest.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include source configs marked enabled=False.",
    )
    return parser.parse_args()


def to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return dict(model)


def dumps_json(row: dict[str, Any], *, indent: bool = False) -> str:
    if orjson is not None:
        option = orjson.OPT_INDENT_2 if indent else 0
        return orjson.dumps(row, option=option).decode("utf-8")
    return json.dumps(row, ensure_ascii=False, indent=2 if indent else None)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(dumps_json(row) + "\n")


def write_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(dumps_json(row, indent=True) + "\n")


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(
    result: dict[str, Any],
    output_path: Path,
    manifest_path: Path,
    report_path: Path,
    rejected_path: Path,
) -> None:
    summary = result["summary"]
    print("Unified KB build complete")
    print(f"Total input records: {summary['total_input_records']}")
    print(f"Accepted records: {summary['total_accepted_records']}")
    print(f"Rejected records: {summary['total_rejected_records']}")
    print(f"Accepted by category: {summary['accepted_by_category']}")
    print(f"Accepted by language: {summary['accepted_by_language']}")
    print(f"Accepted by record_type: {summary['accepted_by_record_type']}")
    print(f"Missing citation count: {summary['missing_citation_count']}")
    print(f"Empty content count: {summary['empty_content_count']}")
    print(f"Unknown record_type count: {summary['unknown_record_type_count']}")
    print(f"KB JSONL: {output_path}")
    print(f"Manifest JSON: {manifest_path}")
    print(f"Report CSV: {report_path}")
    print(f"Rejected JSONL: {rejected_path}")


def main() -> None:
    args = parse_args()
    settings.ensure_directories()

    source_configs = get_default_source_configs()
    if args.include_disabled:
        source_configs = [config.model_copy(update={"enabled": True}) for config in source_configs]
    else:
        source_configs = [config for config in source_configs if config.enabled]

    output_path = resolve_project_path(args.output)
    manifest_path = resolve_project_path(args.manifest)
    report_path = resolve_project_path(args.report)
    rejected_path = resolve_project_path(args.rejected)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = build_unified_kb(source_configs, kb_version=args.kb_version)

    write_jsonl(output_path, [to_dict(record) for record in result["accepted_records"]])
    write_jsonl(rejected_path, [to_dict(record) for record in result["rejected_records"]])
    write_json(manifest_path, to_dict(result["manifest"]))
    write_report(report_path, result["report_rows"])
    print_summary(result, output_path, manifest_path, report_path, rejected_path)


if __name__ == "__main__":
    main()
