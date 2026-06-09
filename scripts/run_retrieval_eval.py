from __future__ import annotations

import argparse
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
BASELINE_RESULTS_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_results_v1.csv"
RERANKED_RESULTS_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_results_reranked_v1.csv"
COMPARISON_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_eval_comparison_v1.csv"
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
    "hit_at_5",
    "first_hit_rank",
    "reciprocal_rank",
    "reranking_enabled",
    "reranking_used",
    "reranking_error",
    "top_title",
    "top_category",
    "top_citation_url",
]

COMPARISON_COLUMNS = [
    "query",
    "expected_category",
    "baseline_hit",
    "reranked_hit",
    "baseline_first_hit_rank",
    "reranked_first_hit_rank",
    "baseline_top_title",
    "reranked_top_title",
    "baseline_reranking_error",
    "reranked_reranking_error",
    "result",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retrieval evaluation.")
    parser.add_argument("--no-rerank", action="store_true", help="Evaluate hybrid retrieval only.")
    parser.add_argument("--rerank", action="store_true", help="Evaluate hybrid retrieval plus reranking.")
    parser.add_argument("--compare", action="store_true", help="Run no-rerank and rerank evals side by side.")
    parser.add_argument("--output", type=Path, default=None, help="Override CSV output path.")
    return parser.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    if args.no_rerank and args.rerank:
        raise SystemExit("Use either --rerank or --no-rerank, not both.")

    ensure_default_golden_file()
    golden_queries = read_jsonl(GOLDEN_PATH)
    if args.compare:
        baseline_rows = run_eval(golden_queries, enable_reranking=False)
        reranked_rows = run_eval(golden_queries, enable_reranking=True)
        output = PROJECT_ROOT / args.output if args.output and not args.output.is_absolute() else (args.output or COMPARISON_PATH)
        comparison_rows = build_comparison_rows(baseline_rows, reranked_rows)
        write_csv(comparison_rows, output, COMPARISON_COLUMNS)
        print("Baseline summary")
        print_summary(baseline_rows)
        print("")
        print("Reranked summary")
        print_summary(reranked_rows)
        print(f"Comparison CSV: {output}")
        return

    enable_reranking = None
    default_output = BASELINE_RESULTS_PATH
    if args.no_rerank:
        enable_reranking = False
    elif args.rerank:
        enable_reranking = True
        default_output = RERANKED_RESULTS_PATH

    rows = run_eval(golden_queries, enable_reranking=enable_reranking)
    output = PROJECT_ROOT / args.output if args.output and not args.output.is_absolute() else (args.output or default_output)
    write_csv(rows, output, CSV_COLUMNS)
    print_summary(rows)
    print(f"Results CSV: {output}")


def run_eval(
    golden_queries: list[dict[str, Any]],
    enable_reranking: bool | None,
) -> list[dict[str, Any]]:
    retriever = HybridRetriever()
    rows: list[dict[str, Any]] = []
    for example in golden_queries:
        try:
            result = retriever.retrieve(example["query"], top_k=TOP_K, enable_reranking=enable_reranking)
        except Exception as exc:
            result = {
                "route": {"route": "error"},
                "final_results": [],
                "reranking_enabled": enable_reranking,
                "reranking_used": False,
                "reranking_error": str(exc),
            }
        rows.append(score_example(example, result))
    return rows


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
    first_hit_rank = first_hit_rank_for_example(example, final_results)
    reciprocal_rank = 1.0 / first_hit_rank if first_hit_rank else 0.0
    hit_at_k = bool(first_hit_rank) or bool(expected_route and expected_route == actual_route)
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
        "hit_at_5": hit_at_k,
        "first_hit_rank": first_hit_rank,
        "reciprocal_rank": reciprocal_rank,
        "reranking_enabled": result.get("reranking_enabled"),
        "reranking_used": result.get("reranking_used"),
        "reranking_error": result.get("reranking_error"),
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
    return any(
        expected_normalized in normalize_match_text(result.get("citation_url") or "")
        for result in results[:TOP_K]
    )


def first_hit_rank_for_example(
    example: dict[str, Any],
    results: list[dict[str, Any]],
) -> int | None:
    if example.get("expected_route") and example["expected_route"] != "retrieval":
        return 1
    expected_category = example.get("expected_category")
    expected_tokens = example.get("expected_contains_any") or []
    expected_citation = example.get("expected_citation_contains")
    for index, result in enumerate(results[:TOP_K], start=1):
        text = normalize_match_text(
            " ".join(str(result.get(key) or "") for key in ("title", "content", "index_text"))
        )
        citation = normalize_match_text(result.get("citation_url") or "")
        category_ok = not expected_category or result.get("category") == expected_category
        text_ok = not expected_tokens or any(normalize_match_text(token) in text for token in expected_tokens)
        citation_ok = not expected_citation or normalize_match_text(expected_citation) in citation
        if category_ok and (text_ok or citation_ok):
            return index
    return None


def normalize_match_text(text: str) -> str:
    normalized = (text or "").lower()
    normalized = normalized.translate(
        str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
    )
    normalized = normalized.replace(",", "")
    normalized = normalized.replace("egp", "le")
    normalized = normalized.replace("\u062c\u0646\u064a\u0647", "le")
    normalized = normalized.replace("\u0642\u0631\u0648\u0634", "pt")
    normalized = normalized.replace("#550*", "*550#")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def build_comparison_rows(
    baseline_rows: list[dict[str, Any]],
    reranked_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    comparison_rows: list[dict[str, Any]] = []
    for baseline, reranked in zip(baseline_rows, reranked_rows, strict=True):
        baseline_rank = baseline.get("first_hit_rank")
        reranked_rank = reranked.get("first_hit_rank")
        comparison_rows.append(
            {
                "query": baseline["query"],
                "expected_category": baseline.get("expected_category"),
                "baseline_hit": baseline.get("hit_at_5"),
                "reranked_hit": reranked.get("hit_at_5"),
                "baseline_first_hit_rank": baseline_rank,
                "reranked_first_hit_rank": reranked_rank,
                "baseline_top_title": baseline.get("top_title"),
                "reranked_top_title": reranked.get("top_title"),
                "baseline_reranking_error": baseline.get("reranking_error"),
                "reranked_reranking_error": reranked.get("reranking_error"),
                "result": compare_ranks(baseline_rank, reranked_rank),
            }
        )
    return comparison_rows


def compare_ranks(baseline_rank: Any, reranked_rank: Any) -> str:
    if baseline_rank in (None, "") and reranked_rank not in (None, ""):
        return "improvement"
    if baseline_rank not in (None, "") and reranked_rank in (None, ""):
        return "regression"
    if baseline_rank in (None, "") and reranked_rank in (None, ""):
        return "unchanged"
    if int(reranked_rank) < int(baseline_rank):
        return "improvement"
    if int(reranked_rank) > int(baseline_rank):
        return "regression"
    return "unchanged"


def write_csv(rows: list[dict[str, Any]], path: Path, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    retrieval_rows = [row for row in rows if row["actual_route"] == "retrieval"]
    route_expected_rows = [row for row in rows if row["expected_route"]]
    route_accuracy = average(row["route_match"] for row in route_expected_rows)
    hit_rate = average(row["hit_at_5"] for row in retrieval_rows)
    category_hit = average(row["category_hit_at_5"] for row in retrieval_rows)
    text_hit = average(row["expected_text_hit_at_5"] for row in retrieval_rows)
    citation_hit = average(row["citation_hit_at_5"] for row in retrieval_rows)
    mrr = average(float(row["reciprocal_rank"] or 0.0) for row in retrieval_rows)
    ranked_hits = [
        int(row["first_hit_rank"])
        for row in retrieval_rows
        if row.get("first_hit_rank") not in (None, "")
    ]
    average_first_rank = sum(ranked_hits) / len(ranked_hits) if ranked_hits else 0.0
    reranking_used_count = sum(1 for row in rows if row.get("reranking_used") is True)
    reranking_error_count = sum(1 for row in rows if row.get("reranking_error"))
    print("Retrieval eval summary")
    print(f"total_queries: {total}")
    print(f"retrieval_queries: {len(retrieval_rows)}")
    print(f"route_accuracy: {route_accuracy:.3f}")
    print(f"hit_rate_at_5: {hit_rate:.3f}")
    print(f"category_hit_at_5: {category_hit:.3f}")
    print(f"expected_text_hit_at_5: {text_hit:.3f}")
    print(f"citation_hit_at_5: {citation_hit:.3f}")
    print(f"mean_reciprocal_rank: {mrr:.3f}")
    print(f"average_rank_of_first_hit: {average_first_rank:.3f}")
    print(f"reranking_used_count: {reranking_used_count}")
    print(f"reranking_error_count: {reranking_error_count}")


def average(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(1.0 if value is True else float(value or 0.0) for value in values) / len(values)


if __name__ == "__main__":
    main()
