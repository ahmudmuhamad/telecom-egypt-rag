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

from src.ingestion.load_official_kb import get_source_configs, resolve_project_path  # noqa: E402


NAVIGATION_TITLES = {
    "home",
    "personal",
    "business",
    "login",
    "my account",
    "search",
    "english",
    "العربية",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Quality-check processed JSONL sources before cloud indexing.")
    parser.add_argument("--sources-config", type=Path, default=Path("config/kb_sources.yaml"))
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--fail-on-errors", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("data/quality/processed_sources_qa_report.csv"))
    parser.add_argument("--summary", type=Path, default=Path("data/quality/processed_sources_qa_summary.json"))
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "__qa_malformed__": True,
                        "line_number": line_number,
                        "error": str(exc),
                    }
                )
                continue
            rows.append(row if isinstance(row, dict) else {"__qa_malformed__": True, "line_number": line_number})
    return rows


def record_issues(row: dict[str, Any]) -> list[str]:
    if row.get("__qa_malformed__"):
        return ["malformed_json"]
    issues: list[str] = []
    title = str(row.get("title") or row.get("question") or row.get("product_name") or row.get("service_name") or "")
    content = str(row.get("content") or "")
    citation_url = str(row.get("citation_url") or row.get("final_url") or row.get("source_url") or "")
    language = str(row.get("language") or "")
    if not title.strip():
        issues.append("missing_title")
    if title.strip().lower() in NAVIGATION_TITLES:
        issues.append("navigation_title")
    if not content.strip():
        issues.append("missing_content")
    elif len(content.strip()) < 80:
        issues.append("short_content")
    if not citation_url.strip():
        issues.append("missing_citation_url")
    if language not in {"", "en", "ar", "mixed", "unknown"}:
        issues.append("unexpected_language")
    if content.lower().count("login") > 3 or content.lower().count("my account") > 3:
        issues.append("possible_navigation_noise")
    return issues


def write_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path = resolve_project_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["source_file", "category", "enabled", "line_number", "title", "citation_url", "issues"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, row: dict[str, Any]) -> None:
    path = resolve_project_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    configs = get_source_configs(args.sources_config)
    if not args.include_disabled:
        configs = [config for config in configs if config.enabled]

    report_rows: list[dict[str, Any]] = []
    summary_sources: list[dict[str, Any]] = []
    total_issues = Counter()
    total_records = 0

    for config in configs:
        source_path = resolve_project_path(config.path)
        rows = load_jsonl(source_path) if source_path.exists() else []
        issue_count = Counter()
        for index, row in enumerate(rows, start=1):
            issues = record_issues(row)
            if issues:
                issue_count.update(issues)
                total_issues.update(issues)
                report_rows.append(
                    {
                        "source_file": str(config.path),
                        "category": config.category,
                        "enabled": config.enabled,
                        "line_number": row.get("line_number") or index,
                        "title": row.get("title") or row.get("question") or row.get("product_name") or "",
                        "citation_url": row.get("citation_url") or row.get("final_url") or row.get("source_url") or "",
                        "issues": ";".join(issues),
                    }
                )
        total_records += len(rows)
        summary_sources.append(
            {
                "category": config.category,
                "path": str(config.path),
                "enabled": config.enabled,
                "exists": source_path.exists(),
                "records": len(rows),
                "issue_counts": dict(sorted(issue_count.items())),
            }
        )

    summary = {
        "total_records": total_records,
        "total_issue_rows": len(report_rows),
        "issue_counts": dict(sorted(total_issues.items())),
        "sources": summary_sources,
    }
    write_report(args.report, report_rows)
    write_json(args.summary, summary)
    print("Processed source QA complete")
    print(f"Records checked: {total_records}")
    print(f"Issue rows: {len(report_rows)}")
    print(f"Report: {resolve_project_path(args.report)}")
    print(f"Summary: {resolve_project_path(args.summary)}")
    if args.fail_on_errors and report_rows:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
