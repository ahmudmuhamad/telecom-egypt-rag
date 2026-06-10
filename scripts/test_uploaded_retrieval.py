from __future__ import annotations

import argparse
import os
import shutil
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ENABLE_GENERATION", "false")

from src.generation.answer_generator import AnswerGenerator  # noqa: E402
from src.ingestion.upload_loader import UploadProcessor  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process a document and query uploaded-document RAG.")
    parser.add_argument("file", type=Path, help="Path to a PDF, DOCX, TXT, HTML, or supported image file.")
    parser.add_argument("query", help="Question to ask over the uploaded document.")
    parser.add_argument("--no-rerank", action="store_true", help="Disable reranking for the retrieval test.")
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

    generator = AnswerGenerator()
    result = generator.answer(
        args.query,
        source_mode="uploads",
        upload_session_id=upload_session_id,
        use_reranking=False if args.no_rerank else None,
    )

    print(f"upload_session_id: {upload_session_id}")
    print(f"document_id: {manifest['document_id']}")
    print(f"file_name: {manifest['file_name']}")
    print("\nAnswer:")
    print(result.get("answer") or "")
    print("\nSources:")
    for source in result.get("sources") or []:
        print(f"[{source.get('source_id')}] {source.get('citation_label')}")


if __name__ == "__main__":
    main()
