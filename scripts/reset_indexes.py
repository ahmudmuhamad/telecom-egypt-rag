from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import ROOT_DIR, settings
from src.services.qdrant_client import get_qdrant_client


INDEX_ARTIFACTS = [
    Path("data/indexes/bm25_official_kb_v1.pkl"),
    Path("data/indexes/bm25_manifest_v1.json"),
    Path("data/indexes/qdrant_index_manifest_v1.json"),
    Path("data/indexes/qdrant_index_report_v1.csv"),
]

KNOWLEDGE_BASE_ARTIFACTS = [
    Path("data/knowledge_base/telecom_egypt_kb_v1.jsonl"),
    Path("data/knowledge_base/kb_manifest_v1.json"),
    Path("data/knowledge_base/kb_build_report_v1.csv"),
    Path("data/knowledge_base/kb_rejected_records_v1.jsonl"),
    Path("data/knowledge_base/telecom_egypt_kb_v1_chunks.jsonl"),
    Path("data/knowledge_base/chunking_report_v1.csv"),
]


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset generated KB/index artifacts.")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument("--qdrant", action="store_true", help="Delete the configured Qdrant collection.")
    parser.add_argument(
        "--knowledge-base",
        action="store_true",
        help="Also delete generated unified KB and chunk artifacts.",
    )
    parser.add_argument("--uploads", action="store_true", help="Also delete files in data/uploads.")
    return parser.parse_args()


def confirm(args: argparse.Namespace, targets: list[Path]) -> bool:
    if args.yes:
        return True
    print("This will delete generated artifacts:")
    for target in targets:
        print(f"  - {resolve_project_path(target)}")
    if args.qdrant:
        print(f"  - Qdrant collection: {settings.qdrant_collection}")
    answer = input("Continue? Type 'yes' to proceed: ")
    return answer.strip().lower() == "yes"


def delete_file(path: Path) -> bool:
    target = resolve_project_path(path)
    if target.exists() and target.is_file():
        target.unlink()
        return True
    return False


def delete_uploads() -> int:
    upload_dir = resolve_project_path(settings.upload_dir)
    deleted = 0
    if not upload_dir.exists():
        return deleted
    for path in upload_dir.iterdir():
        if path.is_file() and path.name != ".gitkeep":
            path.unlink()
            deleted += 1
    return deleted


def delete_qdrant_collection() -> None:
    client = get_qdrant_client()
    if client.collection_exists(settings.qdrant_collection):
        client.delete_collection(settings.qdrant_collection)


def main() -> None:
    args = parse_args()
    targets = list(INDEX_ARTIFACTS)
    if args.knowledge_base:
        targets.extend(KNOWLEDGE_BASE_ARTIFACTS)
    if not confirm(args, targets):
        print("Reset canceled.")
        return

    deleted = 0
    for target in targets:
        deleted += int(delete_file(target))

    upload_deleted = delete_uploads() if args.uploads else 0
    if args.qdrant:
        delete_qdrant_collection()

    print("Reset complete")
    print(f"Deleted files: {deleted}")
    print(f"Deleted uploads: {upload_deleted}")
    if args.qdrant:
        print(f"Deleted Qdrant collection if present: {settings.qdrant_collection}")


if __name__ == "__main__":
    main()
