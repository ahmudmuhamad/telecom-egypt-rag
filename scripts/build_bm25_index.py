from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.indexing.bm25_indexer import build_bm25_index, resolve_project_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the BM25 keyword index.")
    parser.add_argument(
        "--chunks",
        type=Path,
        default=Path("data/knowledge_base/telecom_egypt_kb_v1_chunks.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/indexes/bm25_official_kb_v1.pkl"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/indexes/bm25_manifest_v1.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_bm25_index(
        chunks_path=args.chunks,
        output_path=args.output,
        manifest_path=args.manifest,
    )
    print("BM25 index build complete")
    print(f"Chunks indexed: {manifest['total_chunks']}")
    print(f"Tokenizer: {manifest['tokenizer_version']}")
    print(f"BM25 pickle: {resolve_project_path(args.output)}")
    print(f"Manifest JSON: {resolve_project_path(args.manifest)}")


if __name__ == "__main__":
    main()
