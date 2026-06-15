from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scraping.mobile_post_processor import cleanup_mobile_jsonl  # noqa: E402
from src.scraping.mobile_quality import write_cleanup_report  # noqa: E402


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean WE Mobile post-processed Scrapling records for RAG indexing."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/mobile/mobile_post_processed.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/mobile/mobile_post_processed_cleaned.jsonl"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(
            "data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/"
            "mobile_cleanup_report.csv"
        ),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/"
            "mobile_cleanup_summary.json"
        ),
    )
    parser.add_argument("--overwrite", type=parse_bool, default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.input.exists():
        raise FileNotFoundError(f"Input JSONL does not exist: {args.input}")
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(f"Output exists; pass --overwrite true to replace it: {args.output}")

    records = cleanup_mobile_jsonl(args.input, args.output)
    summary = write_cleanup_report(records, args.report, args.summary)
    print("WE Mobile cleanup complete")
    print(f"Total records: {summary['total_records']}")
    print(f"Accepted records: {summary['accepted_records']}")
    print(f"Rejected records: {summary['rejected_records']}")
    print(f"UI noise removed: {summary['ui_noise_removed_count']}")
    print(f"Kix units extracted: {summary['kix_units_extracted_count']}")
    print(f"Cleaned JSONL: {args.output}")
    print(f"Cleanup CSV: {args.report}")
    print(f"Cleanup summary: {args.summary}")


if __name__ == "__main__":
    main(sys.argv[1:])
