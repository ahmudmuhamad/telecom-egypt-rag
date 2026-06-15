from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings  # noqa: E402
from src.services.qdrant_client import get_qdrant_client  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build KB/BM25/Qdrant on Lightning and export a portable artifact bundle."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/artifacts/cloud_export"))
    parser.add_argument("--bundle", type=Path, default=Path("data/artifacts/cloud_index_bundle.zip"))
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--qdrant-url", default=settings.qdrant_url)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qdrant_version(qdrant_url: str) -> str:
    try:
        response = requests.get(qdrant_url.rstrip("/"), timeout=10)
        response.raise_for_status()
        data = response.json()
        return str(data.get("version") or data.get("title") or "unknown")
    except Exception:
        return "unknown"


def create_and_download_snapshot(
    *,
    qdrant_url: str,
    collection: str,
    output_dir: Path,
) -> Path:
    client = get_qdrant_client()
    snapshot = client.create_snapshot(collection_name=collection, wait=True)
    if snapshot is None or not snapshot.name:
        raise RuntimeError(f"Could not create Qdrant snapshot for collection {collection!r}.")

    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / snapshot.name
    url = f"{qdrant_url.rstrip('/')}/collections/{collection}/snapshots/{snapshot.name}"
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with snapshot_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)
    return snapshot_path


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def build_manifest(output_dir: Path, snapshot_path: Path, qdrant_url: str, collection: str) -> dict[str, object]:
    qdrant_manifest_path = PROJECT_ROOT / "data/indexes/qdrant_index_manifest_v1.json"
    qdrant_manifest = {}
    if qdrant_manifest_path.exists():
        qdrant_manifest = json.loads(qdrant_manifest_path.read_text(encoding="utf-8"))
    files = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(output_dir).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "qdrant_url": qdrant_url,
        "qdrant_version": qdrant_version(qdrant_url),
        "collection": collection,
        "snapshot_file": snapshot_path.relative_to(output_dir).as_posix(),
        "embedding_model": settings.ollama_embedding_model,
        "kb_version": settings.kb_version,
        "index_version": settings.index_version,
        "qdrant_manifest": qdrant_manifest,
        "files": files,
    }


def write_bundle(output_dir: Path, bundle_path: Path) -> None:
    if bundle_path.is_relative_to(output_dir):
        raise ValueError("Bundle path must not be inside output-dir.")
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir).as_posix())


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    bundle = args.bundle if args.bundle.is_absolute() else PROJECT_ROOT / args.bundle
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_step([sys.executable, "scripts/build_unified_kb.py"])
    run_step([sys.executable, "scripts/build_chunks.py"])
    run_step([sys.executable, "scripts/build_bm25_index.py"])
    run_step(
        [
            sys.executable,
            "scripts/build_qdrant_index.py",
            "--recreate",
            "true",
            "--batch-size",
            str(args.batch_size),
        ]
    )
    if not args.skip_tests:
        run_step([sys.executable, "scripts/test_retrieval.py", "هو ايه الDEX Cordless D1005 دا ؟"])
        run_step([sys.executable, "scripts/test_retrieval.py", "كود معرفة الرصيد كام؟"])

    copy_tree(PROJECT_ROOT / "data/knowledge_base", output_dir / "data/knowledge_base")
    copy_tree(PROJECT_ROOT / "data/indexes", output_dir / "data/indexes")
    snapshot_path = create_and_download_snapshot(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        output_dir=output_dir / "qdrant_snapshots",
    )
    manifest = build_manifest(output_dir, snapshot_path, args.qdrant_url, args.collection)
    manifest_path = output_dir / "cloud_artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_bundle(output_dir, bundle)
    print("Cloud artifact build complete")
    print(f"Snapshot: {snapshot_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Bundle: {bundle}")


if __name__ == "__main__":
    main()
