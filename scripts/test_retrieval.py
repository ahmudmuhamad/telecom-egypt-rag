from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.retrieval.hybrid_retriever import HybridRetriever  # noqa: E402
from src.retrieval.source_formatter import make_snippet  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run terminal-testable hybrid retrieval.")
    parser.add_argument("query", help="User query to retrieve Telecom Egypt sources for.")
    parser.add_argument("--top-k", type=int, default=None, help="Override final result count.")
    parser.add_argument("--source-mode", default="official", help="official, uploads, or both.")
    parser.add_argument("--debug", action="store_true", help="Include debug details.")
    parser.add_argument("--show-content", action="store_true", help="Print full chunk content.")
    parser.add_argument("--no-rerank", action="store_true", help="Disable reranking for this run.")
    parser.add_argument("--rerank", action="store_true", help="Force reranking for this run.")
    parser.add_argument("--rerank-top-k", type=int, default=None, help="Override reranking candidate count.")
    parser.add_argument(
        "--show-reranker-text",
        action="store_true",
        help="Print candidate text used by the reranker.",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON.")
    return parser.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    if args.no_rerank and args.rerank:
        raise SystemExit("Use either --rerank or --no-rerank, not both.")
    enable_reranking = None
    if args.no_rerank:
        enable_reranking = False
    elif args.rerank:
        enable_reranking = True

    retriever = HybridRetriever()
    result = retriever.retrieve(
        args.query,
        source_mode=args.source_mode,
        top_k=args.top_k,
        enable_reranking=enable_reranking,
        rerank_top_k=args.rerank_top_k,
        debug=args.debug,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"Query: {result['query']}")
    print_route(result["route"])
    if result["route"]["route"] != "retrieval":
        return

    print(f"Dense count: {len(result['dense_results'])}")
    print(f"BM25 count: {len(result['bm25_results'])}")
    print(f"Boosted count: {len(result.get('boosted_results') or [])}")
    print(f"Reranked count: {len(result.get('reranked_results') or [])}")
    print(f"Final count: {len(result['final_results'])}")
    print(f"Reranking enabled: {str(result.get('reranking_enabled')).lower()}")
    print(f"Reranking used: {str(result.get('reranking_used')).lower()}")
    if result.get("reranking_error"):
        print(f"Reranking error: {result['reranking_error']}")
    if args.debug and result.get("debug"):
        print(f"Debug: {json.dumps(result['debug'], ensure_ascii=False)}")
    print("")

    for item in result["final_results"]:
        print_result(
            item,
            show_content=args.show_content,
            show_reranker_text=args.show_reranker_text,
        )


def print_route(route: dict[str, Any]) -> None:
    decision = route.get("complexity_decision") or {}
    print(f"Route: {route.get('route')}")
    print(f"Reason: {route.get('reason')}")
    print(f"Source mode: {route.get('source_mode')}")
    print(f"Language hint: {route.get('language_hint')}")
    print(f"Category filter: {route.get('category_filter')}")
    print(f"Metadata filters: {route.get('metadata_filters')}")
    print(
        "Complexity/pipeline: "
        f"{decision.get('complexity')} / {decision.get('pipeline_mode')} "
        f"(dense={decision.get('dense_top_k')}, bm25={decision.get('bm25_top_k')}, "
        f"rerank={decision.get('rerank_top_k')}, final={decision.get('final_top_k')})"
    )


def print_result(
    result: dict[str, Any],
    show_content: bool = False,
    show_reranker_text: bool = False,
) -> None:
    print(f"Rank {result.get('rank')}")
    print(f"Pre-rerank rank: {result.get('pre_rerank_rank')}")
    print(f"Title: {result.get('title')}")
    print(f"Category: {result.get('category')}")
    print(f"Record type: {result.get('record_type')}")
    print(f"Language: {result.get('language')}")
    print(f"Final score: {float(result.get('final_score') or 0.0):.6f}")
    print(f"Reranker score: {format_optional_score(result.get('reranker_score'))}")
    print(f"Pre-rerank score: {format_optional_score(result.get('pre_rerank_score'))}")
    print(f"RRF score: {float(result.get('rrf_score') or 0.0):.6f}")
    print(f"Boost score: {float(result.get('boost_score') or 0.0):.6f}")
    print(f"Dense score: {format_optional_score(result.get('dense_score'))}")
    print(f"BM25 score: {format_optional_score(result.get('bm25_score'))}")
    print(f"Citation: {result.get('citation_url')}")
    print(f"Snippet: {make_snippet(result.get('content') or result.get('index_text') or '')}")
    if show_content:
        print("Content:")
        print(result.get("content") or "")
    if show_reranker_text and result.get("reranker_text"):
        print("Reranker text:")
        print(result["reranker_text"])
    print("")


def format_optional_score(score: Any) -> str:
    return "n/a" if score is None else f"{float(score):.6f}"


if __name__ == "__main__":
    main()
