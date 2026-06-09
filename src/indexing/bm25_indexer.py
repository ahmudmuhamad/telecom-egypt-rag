from __future__ import annotations

import json
import pickle
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from config.settings import ROOT_DIR, settings


TOKENIZER_VERSION = "telecom_regex_v1"
TOKEN_PATTERN = re.compile(r"\*[\w*#]+\#?|\d[\d,]*(?:\.\d+)?|[\w\u0600-\u06FF]+", re.UNICODE)


def resolve_project_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT_DIR / path


def tokenize_for_bm25(text: str) -> list[str]:
    tokens = TOKEN_PATTERN.findall(text or "")
    return [token.lower() if token.isascii() else token for token in tokens]


def load_chunks(path: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    with resolve_project_path(path).open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(json.loads(line))
    return chunks


def write_json(path: Path, row: dict[str, Any]) -> None:
    output = resolve_project_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as file:
        json.dump(row, file, ensure_ascii=False, indent=2)
        file.write("\n")


def build_bm25_index(
    chunks_path: Path,
    output_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    chunks = load_chunks(chunks_path)
    if not chunks:
        raise RuntimeError(f"No chunks found in {chunks_path}.")

    tokenized_corpus = [tokenize_for_bm25(chunk.get("index_text") or "") for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    chunk_refs = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "parent_record_id": chunk.get("parent_record_id"),
            "category": chunk.get("category"),
            "record_type": chunk.get("record_type"),
            "language": chunk.get("language"),
            "title": chunk.get("title"),
            "citation_url": chunk.get("citation_url"),
            "chunk_index": chunk.get("chunk_index"),
            "total_chunks": chunk.get("total_chunks"),
            "metadata": chunk.get("metadata") or {},
        }
        for chunk in chunks
    ]

    artifact = {
        "bm25": bm25,
        "chunks": chunk_refs,
        "tokenized_corpus": tokenized_corpus,
        "index_version": settings.index_version,
        "kb_version": chunks[0].get("kb_version"),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.ollama_embedding_model,
        "tokenizer_version": TOKENIZER_VERSION,
        "source_chunks_file": str(chunks_path),
    }

    output = resolve_project_path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as file:
        pickle.dump(artifact, file)

    manifest = {
        "kb_version": chunks[0].get("kb_version"),
        "index_version": settings.index_version,
        "total_chunks": len(chunks),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tokenizer_version": TOKENIZER_VERSION,
        "source_chunks_file": str(chunks_path),
    }
    write_json(manifest_path, manifest)
    return manifest
