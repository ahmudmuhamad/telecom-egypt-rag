from __future__ import annotations

from qdrant_client import QdrantClient

from config.settings import settings


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def qdrant_health_check() -> bool:
    try:
        get_qdrant_client().get_collections()
        return True
    except Exception:
        return False


def collection_exists(collection_name: str) -> bool:
    try:
        return get_qdrant_client().collection_exists(collection_name)
    except Exception:
        return False


def list_collections() -> list[str]:
    collections = get_qdrant_client().get_collections().collections
    return [collection.name for collection in collections]
