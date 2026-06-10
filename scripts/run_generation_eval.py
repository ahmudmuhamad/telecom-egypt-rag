from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.generation.answer_generator import AnswerGenerator  # noqa: E402


GOLDEN_PATH = PROJECT_ROOT / "data" / "evaluation" / "golden_queries_v1.jsonl"
RESULTS_PATH = PROJECT_ROOT / "data" / "evaluation" / "generation_eval_results_v1.csv"

DEFAULT_GOLDEN_QUERIES: list[dict[str, Any]] = [
    {
        "query": "كود معرفة الرصيد كام؟",
        "expected_category": "services",
        "expected_contains_any": ["550", "*550", "#550"],
        "expected_citation_contains": "balance",
    },
    {
        "query": "What is the SIM swap cost?",
        "expected_category": "faq",
        "expected_contains_any": ["5", "LE", "SIM"],
        "expected_citation_contains": "faq",
    },
    {
        "query": "What are WE Space recharge add-ons?",
        "expected_category": "we_home",
        "expected_contains_any": ["20 GB", "50 GB", "100 GB", "60 EGP", "120 EGP", "190 EGP"],
        "expected_citation_contains": "we-space",
    },
    {
        "query": "Compare Vodafone and WE prices",
        "expected_route": "rejection",
    },
]

CSV_COLUMNS = [
    "query_id",
    "query",
    "route",
    "expected_route",
    "model_used",
    "model_tier",
    "generation_used",
    "fallback_used",
    "answer",
    "source_count",
    "has_valid_citations",
    "expected_category",
    "expected_contains_any",
    "answer_contains_expected",
    "citation_hit",
    "error",
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ensure_default_golden_file()
    golden_queries = read_jsonl(GOLDEN_PATH)
    generator = AnswerGenerator()
    rows: list[dict[str, Any]] = []
    for query_id, example in enumerate(golden_queries, start=1):
        rows.append(evaluate_example(query_id, example, generator))
    write_csv(rows)
    print_summary(rows)
    print(f"Results CSV: {RESULTS_PATH}")


def ensure_default_golden_file() -> None:
    if GOLDEN_PATH.exists():
        return
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with GOLDEN_PATH.open("w", encoding="utf-8") as file:
        for row in DEFAULT_GOLDEN_QUERIES:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def evaluate_example(
    query_id: int,
    example: dict[str, Any],
    generator: AnswerGenerator,
) -> dict[str, Any]:
    try:
        result = generator.answer(example["query"], use_reranking=False)
    except Exception as exc:
        result = {
            "route": {"route": "error"},
            "answer": "",
            "sources": [],
            "validation": {"valid": False},
            "error": str(exc),
        }
    answer = result.get("answer") or ""
    sources = result.get("sources") or []
    expected_tokens = example.get("expected_contains_any") or []
    expected_citation = example.get("expected_citation_contains")
    return {
        "query_id": query_id,
        "query": example.get("query"),
        "route": result.get("route", {}).get("route"),
        "expected_route": example.get("expected_route"),
        "model_used": result.get("model_used"),
        "model_tier": result.get("model_tier"),
        "generation_used": result.get("generation_used"),
        "fallback_used": result.get("fallback_used"),
        "answer": answer,
        "source_count": len(sources),
        "has_valid_citations": bool((result.get("validation") or {}).get("valid")),
        "expected_category": example.get("expected_category"),
        "expected_contains_any": "|".join(expected_tokens),
        "answer_contains_expected": contains_any(answer, expected_tokens),
        "citation_hit": citation_hit(sources, expected_citation),
        "error": result.get("error"),
    }


def contains_any(text: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    normalized = normalize_match_text(text)
    return any(normalize_match_text(token) in normalized for token in tokens)


def citation_hit(sources: list[dict[str, Any]], expected: str | None) -> bool:
    if not expected:
        return True
    expected = normalize_match_text(expected)
    return any(expected in normalize_match_text(source.get("citation_url") or "") for source in sources)


def normalize_match_text(text: str) -> str:
    normalized = (text or "").lower()
    normalized = normalized.translate(
        str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
    )
    normalized = normalized.replace(",", "")
    normalized = normalized.replace("egp", "le")
    normalized = normalized.replace("جنيه", "le")
    normalized = normalized.replace("قروش", "pt")
    normalized = normalized.replace("#550*", "*550#")
    return re.sub(r"\s+", " ", normalized).strip()


def write_csv(rows: list[dict[str, Any]]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    generation_rows = [row for row in rows if row["route"] == "retrieval"]
    route_expected = [row for row in rows if row["expected_route"]]
    route_accuracy = average(row["route"] == row["expected_route"] for row in route_expected)
    citation_rate = average(row["has_valid_citations"] for row in generation_rows)
    answer_hit_rate = average(row["answer_contains_expected"] for row in generation_rows)
    citation_hit_rate = average(row["citation_hit"] for row in generation_rows)
    fallback_count = sum(1 for row in rows if row["fallback_used"] is True)
    error_count = sum(1 for row in rows if row["error"])
    print("Generation eval summary")
    print(f"total_queries: {total}")
    print(f"retrieval_generation_queries: {len(generation_rows)}")
    print(f"route_accuracy: {route_accuracy:.3f}")
    print(f"citation_validity_rate: {citation_rate:.3f}")
    print(f"expected_text_answer_hit_rate: {answer_hit_rate:.3f}")
    print(f"citation_hit_rate: {citation_hit_rate:.3f}")
    print(f"generation_error_count: {error_count}")
    print(f"fallback_count: {fallback_count}")


def average(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(1.0 if value is True else float(value or 0.0) for value in values) / len(values)


if __name__ == "__main__":
    main()
