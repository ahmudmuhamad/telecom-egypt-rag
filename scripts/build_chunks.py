from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
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
from src.ingestion.chunking import chunk_record, is_atomic_record
from src.ingestion.load_official_kb import resolve_project_path


REPORT_COLUMNS = [
    "record_id",
    "chunk_id",
    "category",
    "record_type",
    "language",
    "title",
    "citation_url",
    "original_content_length",
    "chunk_content_length",
    "chunk_index",
    "total_chunks",
    "is_atomic",
    "status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build chunks from the unified official KB.")
    parser.add_argument("--input", type=Path, default=Path("data/knowledge_base/telecom_egypt_kb_v1.jsonl"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/knowledge_base/telecom_egypt_kb_v1_chunks.jsonl"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/knowledge_base/chunking_report_v1.csv"),
    )
    parser.add_argument("--chunk-size", type=int, default=settings.chunk_size)
    parser.add_argument("--chunk-overlap", type=int, default=settings.chunk_overlap)
    return parser.parse_args()


def dumps_json(row: dict[str, Any]) -> str:
    if orjson is not None:
        return orjson.dumps(row).decode("utf-8")
    return json.dumps(row, ensure_ascii=False)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(dumps_json(row) + "\n")


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_path = resolve_project_path(args.input)
    output_path = resolve_project_path(args.output)
    report_path = resolve_project_path(args.report)

    records = load_jsonl(input_path)
    chunks: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    atomic_count = 0
    split_count = 0
    max_chunks = 0

    for record in records:
        record_is_atomic = is_atomic_record({**record, "_chunk_size": args.chunk_size})
        record_chunks = chunk_record(record, args.chunk_size, args.chunk_overlap)
        chunks.extend(record_chunks)
        max_chunks = max(max_chunks, len(record_chunks))
        atomic_count += int(record_is_atomic)
        split_count += int(not record_is_atomic and len(record_chunks) > 1)
        for chunk in record_chunks:
            report_rows.append(
                {
                    "record_id": record.get("record_id"),
                    "chunk_id": chunk.get("chunk_id"),
                    "category": chunk.get("category"),
                    "record_type": chunk.get("record_type"),
                    "language": chunk.get("language") or "",
                    "title": chunk.get("title"),
                    "citation_url": chunk.get("citation_url"),
                    "original_content_length": len(record.get("content") or ""),
                    "chunk_content_length": len(chunk.get("content") or ""),
                    "chunk_index": chunk.get("chunk_index"),
                    "total_chunks": chunk.get("total_chunks"),
                    "is_atomic": record_is_atomic,
                    "status": "ok",
                }
            )

    write_jsonl(output_path, chunks)
    write_report(report_path, report_rows)

    by_category = Counter(chunk.get("category") for chunk in chunks)
    by_record_type = Counter(chunk.get("record_type") for chunk in chunks)
    print("Chunk build complete")
    print(f"Input records: {len(records)}")
    print(f"Output chunks: {len(chunks)}")
    print(f"Chunks by category: {dict(sorted(by_category.items()))}")
    print(f"Chunks by record_type: {dict(sorted(by_record_type.items()))}")
    print(f"Atomic records count: {atomic_count}")
    print(f"Split records count: {split_count}")
    print(f"Max chunks per record: {max_chunks}")
    print(f"Chunks JSONL: {output_path}")
    print(f"Report CSV: {report_path}")


if __name__ == "__main__":
    main()
