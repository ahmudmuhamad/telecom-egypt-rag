from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.indexing.qdrant_indexer import QdrantIndexer, resolve_project_path


def parse_bool(value: str) -> bool:
    normalized = value.lower().strip()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected true or false.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Qdrant dense vector index.")
    parser.add_argument(
        "--chunks",
        type=Path,
        default=Path("data/knowledge_base/telecom_egypt_kb_v1_chunks.jsonl"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/indexes/qdrant_index_manifest_v1.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/indexes/qdrant_index_report_v1.csv"),
    )
    parser.add_argument("--recreate", type=parse_bool, default=True)
    parser.add_argument("--batch-size", type=int, default=16)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    indexer = QdrantIndexer()
    manifest = indexer.build_index(
        chunks_path=args.chunks,
        manifest_path=args.manifest,
        report_path=args.report,
        recreate=args.recreate,
        batch_size=args.batch_size,
    )
    print("Qdrant index build complete")
    print(f"Collection: {manifest['collection_name']}")
    print(f"Chunks indexed: {manifest['total_chunks_indexed']}")
    print(f"Vector size: {manifest['vector_size']}")
    print(f"Manifest JSON: {resolve_project_path(args.manifest)}")
    print(f"Report CSV: {resolve_project_path(args.report)}")


if __name__ == "__main__":
    main()
