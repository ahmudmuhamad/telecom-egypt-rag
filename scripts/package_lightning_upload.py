from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_INCLUDE_PATHS = (
    "app",
    "config",
    "scripts",
    "src",
    "data/processed",
    "data/scrape_mobile_scrapling_v1/04_quality_reports",
    "data/scrape_public_site_v1/04_quality_reports",
    "docs",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "README.md",
)
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    ".uv-cache",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data/indexes",
    "data/knowledge_base",
    "data/uploads",
    "data/logs",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package local scraped data/code for Lightning AI indexing.")
    parser.add_argument("--output", type=Path, default=Path("data/artifacts/lightning_upload_bundle.zip"))
    parser.add_argument("--include", nargs="*", default=list(DEFAULT_INCLUDE_PATHS))
    return parser.parse_args()


def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & EXCLUDE_PARTS)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = PROJECT_ROOT / raw
        if not path.exists():
            continue
        if path.is_file():
            files.append(path)
            continue
        for child in path.rglob("*"):
            if child.is_file() and not should_exclude(child.relative_to(PROJECT_ROOT)):
                files.append(child)
    return sorted(set(files))


def main() -> None:
    args = parse_args()
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    files = iter_files(args.include)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Upload to Lightning AI for KB/chunk/BM25/Qdrant build.",
        "excluded": sorted(EXCLUDE_PARTS),
        "files": [],
    }
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            relative = file_path.relative_to(PROJECT_ROOT).as_posix()
            archive.write(file_path, relative)
            manifest["files"].append(
                {
                    "path": relative,
                    "bytes": file_path.stat().st_size,
                    "sha256": sha256_file(file_path),
                }
            )
        archive.writestr("cloud_upload_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print("Lightning upload bundle created")
    print(f"Files: {len(files)}")
    print(f"Bundle: {output}")


if __name__ == "__main__":
    main()
