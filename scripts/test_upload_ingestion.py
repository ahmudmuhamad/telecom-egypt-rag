from __future__ import annotations

import argparse
import shutil
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.upload_loader import UploadProcessor  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process one uploaded document into upload RAG indexes.")
    parser.add_argument("file", type=Path, help="Path to a PDF, DOCX, TXT, HTML, or supported image file.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_path = args.file
    if not source_path.exists():
        raise SystemExit(f"File not found: {source_path}")

    upload_session_id = f"test_{uuid.uuid4().hex[:12]}"
    processor = UploadProcessor(upload_session_id)
    processor.original_dir.mkdir(parents=True, exist_ok=True)
    safe_name = processor.sanitize_file_name(source_path.name)
    stored_path = processor.original_dir / safe_name
    shutil.copy2(source_path, stored_path)

    manifest = processor.process_file(stored_path)
    print(f"upload_session_id: {upload_session_id}")
    print(f"document_id: {manifest['document_id']}")
    print(f"file_name: {manifest['file_name']}")
    print(f"chunks_count: {manifest['chunks_count']}")
    print(f"bm25_index_path: {manifest['bm25_index_path']}")
    print(f"qdrant_upsert_status: {manifest['qdrant_status'].get('chunks_indexed_this_run', 0)}")


if __name__ == "__main__":
    main()
