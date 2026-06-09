from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from config.settings import settings


class ExactQueryCache:
    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        return self._cache.get(key)

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()


@dataclass(frozen=True)
class SemanticCacheConfig:
    enabled: bool = settings.enable_semantic_cache
    threshold: float = settings.semantic_cache_threshold
    collection_name: str = settings.semantic_cache_collection


class SemanticCachePlaceholder:
    def __init__(self, config: SemanticCacheConfig | None = None) -> None:
        self.config = config or SemanticCacheConfig()

    def get_similar(self, query: str) -> dict[str, Any] | None:
        # Future design: embed the query, search the semantic cache collection,
        # validate matches above the threshold, optionally rerank, then return
        # the cached answer.
        return None

    def set(self, query: str, value: dict[str, Any]) -> None:
        # Future design: store the query embedding and answer payload in Qdrant.
        return None


class EmbeddingCache:
    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def hash_text(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get(self, text: str) -> list[float] | None:
        return self._cache.get(self.hash_text(text))

    def set(self, text: str, embedding: list[float]) -> None:
        self._cache[self.hash_text(text)] = embedding


class PromptCachePlaceholder:
    def get(self, key: str) -> dict[str, Any] | None:
        # Future design: cache stable system prompt and context prefixes when
        # supported by the selected model runtime.
        return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        return None
