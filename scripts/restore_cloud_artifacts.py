from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore a Lightning-built KB/BM25/Qdrant snapshot bundle into local Docker Qdrant."
    )
    parser.add_argument("artifact", type=Path, help="cloud_index_bundle.zip or extracted artifact directory.")
    parser.add_argument("--qdrant-url", default=settings.qdrant_url)
    parser.add_argument("--collection", default=settings.qdrant_collection)
    parser.add_argument("--skip-snapshot", action="store_true")
    return parser.parse_args()


def prepare_artifact(path: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    artifact = path if path.is_absolute() else PROJECT_ROOT / path
    if artifact.is_dir():
        return artifact, None
    temp = tempfile.TemporaryDirectory()
    with ZipFile(artifact, "r") as archive:
        archive.extractall(temp.name)
    return Path(temp.name), temp


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Missing artifact directory: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def find_snapshot(artifact_dir: Path) -> Path:
    snapshots = sorted((artifact_dir / "qdrant_snapshots").glob("*.snapshot"))
    if not snapshots:
        snapshots = sorted((artifact_dir / "qdrant_snapshots").glob("*"))
    if not snapshots:
        raise FileNotFoundError("No Qdrant snapshot found under qdrant_snapshots/.")
    return snapshots[0]


def upload_snapshot(qdrant_url: str, collection: str, snapshot_path: Path) -> None:
    url_base = qdrant_url.rstrip("/")
    endpoints = (
        f"{url_base}/collections/{collection}/snapshots/upload?priority=snapshot",
        f"{url_base}/collections/{collection}/snapshots/upload",
    )
    last_error: Exception | None = None
    for endpoint in endpoints:
        for method in (requests.post, requests.put):
            try:
                with snapshot_path.open("rb") as file:
                    response = method(
                        endpoint,
                        files={"snapshot": (snapshot_path.name, file, "application/octet-stream")},
                        timeout=300,
                    )
                if response.status_code in {200, 202}:
                    return
                last_error = RuntimeError(f"{response.status_code}: {response.text[:500]}")
            except Exception as exc:
                last_error = exc
    raise RuntimeError(f"Could not upload Qdrant snapshot: {last_error}")


def main() -> None:
    args = parse_args()
    artifact_dir, temp = prepare_artifact(args.artifact)
    try:
        manifest_path = artifact_dir / "cloud_artifact_manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            print(f"Artifact collection: {manifest.get('collection')}")
            print(f"Embedding model: {manifest.get('embedding_model')}")
            print(f"Qdrant version: {manifest.get('qdrant_version')}")

        copy_tree(artifact_dir / "data/knowledge_base", PROJECT_ROOT / "data/knowledge_base")
        copy_tree(artifact_dir / "data/indexes", PROJECT_ROOT / "data/indexes")
        print("Restored data/knowledge_base and data/indexes.")

        if not args.skip_snapshot:
            snapshot_path = find_snapshot(artifact_dir)
            upload_snapshot(args.qdrant_url, args.collection, snapshot_path)
            print(f"Uploaded Qdrant snapshot to collection {args.collection}: {snapshot_path.name}")
    finally:
        if temp is not None:
            temp.cleanup()


if __name__ == "__main__":
    main()
