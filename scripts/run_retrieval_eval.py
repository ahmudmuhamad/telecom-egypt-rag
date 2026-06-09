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

from src.retrieval.hybrid_retriever import HybridRetriever  # noqa: E402


GOLDEN_PATH = PROJECT_ROOT / "data" / "evaluation" / "golden_queries_v1.jsonl"
RESULTS_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_results_v1.csv"
TOP_K = 5

DEFAULT_GOLDEN_QUERIES: list[dict[str, Any]] = [
    {
        "query": "كود معرفة الرصيد كام؟",
        "expected_category": "services",
        "expected_contains_any": ["550", "*550", "#550"],
        "expected_citation_contains": "balance",
    },
    {
        "query": "ازاي أعرف رصيدي؟",
        "expected_category": "services",
        "expected_contains_any": ["550", "رصيد", "balance"],
        "expected_citation_contains": "balance",
    },
    {
        "query": "What is the SIM swap cost?",
        "expected_category": "faq",
        "expected_contains_any": ["5", "LE", "SIM"],
        "expected_citation_contains": "faq",
    },
    {
        "query": "What is the yearly fee for WE Space Mega 3000 GB?",
        "expected_category": "we_home",
        "expected_contains_any": ["6490", "6,490", "3,000 GB", "3000 GB", "70 Mbps"],
        "expected_citation_contains": "we-space",
    },
    {
        "query": "What are WE Space recharge add-ons?",
        "expected_category": "we_home",
        "expected_contains_any": ["20 GB", "50 GB", "100 GB", "60 EGP", "120 EGP", "190 EGP"],
        "expected_citation_contains": "we-space",
    },
    {
        "query": "سعر راوتر TP-Link كام؟",
        "expected_category": "devices",
        "expected_contains_any": ["TP", "Link", "EGP", "جنيه"],
        "expected_citation_contains": "devices",
    },
    {
        "query": "What is the customer service number?",
        "expected_category": None,
        "expected_contains_any": ["111"],
        "expected_citation_contains": None,
    },
    {
        "query": "What is WE Air prepaid?",
        "expected_category": "we_home",
        "expected_contains_any": ["WE Air", "290", "GB"],
        "expected_citation_contains": "we-air",
    },
    {
        "query": "ما هي مواعيد سداد فاتورة الخط الأرضي؟",
        "expected_category": "faq",
        "expected_contains_any": ["20", "21", "25"],
        "expected_citation_contains": "fixed-voice",
    },
    {
        "query": "Compare Vodafone and WE prices",
        "expected_route": "rejection",
    },
]

CSV_COLUMNS = [
    "query",
    "expected_route",
    "actual_route",
    "route_match",
    "expected_category",
    "category_hit_at_5",
    "expected_contains_any",
    "expected_text_hit_at_5",
    "expected_citation_contains",
    "citation_hit_at_5",
    "reciprocal_rank",
    "top_title",
    "top_category",
    "top_citation_url",
]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ensure_default_golden_file()
    golden_queries = read_jsonl(GOLDEN_PATH)
    retriever = HybridRetriever()
    rows: list[dict[str, Any]] = []

    for example in golden_queries:
        result = retriever.retrieve(example["query"], top_k=TOP_K, debug=False)
        rows.append(score_example(example, result))

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


def score_example(example: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    final_results = result.get("final_results") or []
    expected_route = example.get("expected_route")
    actual_route = result.get("route", {}).get("route")
    route_match = expected_route is None or expected_route == actual_route
    category_hit = category_hit_at_k(final_results, example.get("expected_category"))
    text_hit = expected_text_hit_at_k(final_results, example.get("expected_contains_any") or [])
    citation_hit = citation_hit_at_k(final_results, example.get("expected_citation_contains"))
    reciprocal_rank = reciprocal_rank_for_example(example, final_results)
    top_result = final_results[0] if final_results else {}
    return {
        "query": example.get("query"),
        "expected_route": expected_route,
        "actual_route": actual_route,
        "route_match": route_match,
        "expected_category": example.get("expected_category"),
        "category_hit_at_5": category_hit,
        "expected_contains_any": "|".join(example.get("expected_contains_any") or []),
        "expected_text_hit_at_5": text_hit,
        "expected_citation_contains": example.get("expected_citation_contains"),
        "citation_hit_at_5": citation_hit,
        "reciprocal_rank": reciprocal_rank,
        "top_title": top_result.get("title"),
        "top_category": top_result.get("category"),
        "top_citation_url": top_result.get("citation_url"),
    }


def category_hit_at_k(results: list[dict[str, Any]], expected_category: str | None) -> bool:
    if not expected_category:
        return True
    return any(result.get("category") == expected_category for result in results[:TOP_K])


def expected_text_hit_at_k(results: list[dict[str, Any]], expected_tokens: list[str]) -> bool:
    if not expected_tokens:
        return True
    haystack = normalize_match_text(
        " ".join(
            " ".join(str(result.get(key) or "") for key in ("title", "content", "index_text"))
            for result in results[:TOP_K]
        )
    )
    return any(normalize_match_text(token) in haystack for token in expected_tokens)


def citation_hit_at_k(results: list[dict[str, Any]], expected: str | None) -> bool:
    if not expected:
        return True
    expected_normalized = normalize_match_text(expected)
    return any(expected_normalized in normalize_match_text(result.get("citation_url") or "") for result in results[:TOP_K])


def reciprocal_rank_for_example(
    example: dict[str, Any],
    results: list[dict[str, Any]],
) -> float:
    expected_category = example.get("expected_category")
    expected_tokens = example.get("expected_contains_any") or []
    expected_citation = example.get("expected_citation_contains")
    if example.get("expected_route") and example["expected_route"] != "retrieval":
        return 1.0
    for index, result in enumerate(results[:TOP_K], start=1):
        text = normalize_match_text(
            " ".join(str(result.get(key) or "") for key in ("title", "content", "index_text"))
        )
        citation = normalize_match_text(result.get("citation_url") or "")
        category_ok = not expected_category or result.get("category") == expected_category
        text_ok = not expected_tokens or any(normalize_match_text(token) in text for token in expected_tokens)
        citation_ok = not expected_citation or normalize_match_text(expected_citation) in citation
        if category_ok and (text_ok or citation_ok):
            return 1.0 / index
    return 0.0


def normalize_match_text(text: str) -> str:
    normalized = (text or "").lower()
    normalized = normalized.translate(str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789"))
    normalized = normalized.replace(",", "")
    normalized = normalized.replace("egp", "le")
    normalized = normalized.replace("\u062c\u0646\u064a\u0647", "le")
    normalized = normalized.replace("\u0642\u0631\u0648\u0634", "pt")
    normalized = normalized.replace("#550*", "*550#")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def write_csv(rows: list[dict[str, Any]]) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    retrieval_rows = [row for row in rows if row["actual_route"] == "retrieval"]
    route_expected_rows = [row for row in rows if row["expected_route"]]
    route_accuracy = average(row["route_match"] for row in route_expected_rows)
    category_hit = average(row["category_hit_at_5"] for row in retrieval_rows)
    text_hit = average(row["expected_text_hit_at_5"] for row in retrieval_rows)
    citation_hit = average(row["citation_hit_at_5"] for row in retrieval_rows)
    hit_rate = average(
        row["category_hit_at_5"] and row["expected_text_hit_at_5"] and row["citation_hit_at_5"]
        for row in retrieval_rows
    )
    mrr = average(float(row["reciprocal_rank"] or 0.0) for row in retrieval_rows)
    print("Retrieval eval summary")
    print(f"total_queries: {total}")
    print(f"retrieval_queries: {len(retrieval_rows)}")
    print(f"route_accuracy: {route_accuracy:.3f}")
    print(f"hit_rate_at_5: {hit_rate:.3f}")
    print(f"category_hit_at_5: {category_hit:.3f}")
    print(f"expected_text_hit_at_5: {text_hit:.3f}")
    print(f"citation_hit_at_5: {citation_hit:.3f}")
    print(f"mean_reciprocal_rank: {mrr:.3f}")


def average(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(1.0 if value is True else float(value or 0.0) for value in values) / len(values)


if __name__ == "__main__":
    main()
