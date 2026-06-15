from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.generation.answer_generator import AnswerGenerator  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run terminal RAG answer generation.")
    parser.add_argument("query", help="Question to answer from official Telecom Egypt sources.")
    parser.add_argument("--source-mode", default="official", help="official, uploads, or both.")
    parser.add_argument("--top-k", type=int, default=None, help="Override final retrieval result count.")
    parser.add_argument("--rerank", action="store_true", help="Force reranking for retrieval.")
    parser.add_argument("--no-rerank", action="store_true", help="Disable reranking for retrieval.")
    parser.add_argument("--debug", action="store_true", help="Include full retrieval object.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument("--show-sources", action="store_true", help="Print source cards.")
    parser.add_argument("--show-retrieval", action="store_true", help="Print compact retrieval details.")
    return parser.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args = parse_args()
    if args.rerank and args.no_rerank:
        raise SystemExit("Use either --rerank or --no-rerank, not both.")
    use_reranking = None
    if args.rerank:
        use_reranking = True
    elif args.no_rerank:
        use_reranking = False

    generator = AnswerGenerator()
    result = generator.answer(
        args.query,
        source_mode=args.source_mode,
        top_k=args.top_k,
        use_reranking=use_reranking,
        debug=args.debug or args.json,
    )
    if args.debug or args.json:
        retrieval = result.get("retrieval") or {}
        route = result.get("route") or {}
        result["debug_comparison"] = {
            "retrieval_final_result_titles": [
                item.get("title") for item in retrieval.get("final_results") or []
            ],
            "final_source_titles": [source.get("title") for source in result.get("sources") or []],
            "reranking_used": retrieval.get("reranking_used"),
            "source_mode": route.get("source_mode"),
            "category_filter": route.get("category_filter"),
            "raw_model_answer": result.get("raw_model_answer"),
            "validation_reason": result.get("validation_error")
            or (result.get("validation") or {}).get("reason"),
        }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"Query: {result['query']}")
    print(f"Route: {result.get('route', {}).get('route')}")
    print(f"Model used: {result.get('model_used') or 'n/a'}")
    print(f"Model tier: {result.get('model_tier') or 'n/a'}")
    print(f"Generation used: {str(result.get('generation_used')).lower()}")
    print(f"Fallback used: {str(result.get('fallback_used')).lower()}")
    validation = result.get("validation") or {}
    print(f"Validation valid: {str(validation.get('valid')).lower()}")
    print(f"Validation reason: {validation.get('reason')}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print("")
    print("Answer:")
    print(result.get("answer_with_sources") or result.get("answer") or "")

    if args.show_sources:
        print("")
        print("Source cards:")
        for source in result.get("sources") or []:
            print_source(source)

    if args.show_retrieval:
        print("")
        print("Retrieval:")
        print(json.dumps(result.get("retrieval") or {}, ensure_ascii=False, indent=2))


def print_source(source: dict[str, Any]) -> None:
    print(f"[{source.get('source_id')}] {source.get('citation_label')}")
    print(f"Title: {source.get('title')}")
    print(f"Category: {source.get('category')}")
    print(f"Record type: {source.get('record_type')}")
    print(f"URL: {source.get('citation_url')}")
    print(f"Snippet: {source.get('snippet')}")
    print("")


if __name__ == "__main__":
    main()
