from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram


RAG_QUERIES_TOTAL = Counter(
    "rag_queries_total",
    "Total RAG queries handled.",
    ["route", "source_mode", "language"],
)
RAG_ANSWERS_WITH_CITATIONS_TOTAL = Counter(
    "rag_answers_with_citations_total",
    "Total answers that include citations.",
)
RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL = Counter(
    "rag_answers_without_citations_total",
    "Total answers that do not include citations.",
)
RAG_UPLOADS_TOTAL = Counter(
    "rag_uploads_total",
    "Total uploaded files accepted for processing.",
    ["file_type"],
)
RAG_UPLOAD_FAILURES_TOTAL = Counter(
    "rag_upload_failures_total",
    "Total upload processing failures.",
    ["file_type"],
)
RAG_CACHE_HITS_TOTAL = Counter(
    "rag_cache_hits_total",
    "Total cache hits.",
    ["cache_type"],
)
RAG_CACHE_MISSES_TOTAL = Counter(
    "rag_cache_misses_total",
    "Total cache misses.",
    ["cache_type"],
)
RAG_MODEL_ROUTING_TOTAL = Counter(
    "rag_model_routing_total",
    "Total model routing decisions.",
    ["model_tier", "model_name", "pipeline_mode"],
)
RAG_FALLBACKS_TOTAL = Counter(
    "rag_fallbacks_total",
    "Total fallback events.",
    ["reason"],
)

RAG_TOTAL_LATENCY = Histogram("rag_total_latency_seconds", "End-to-end RAG latency.")
RAG_RETRIEVAL_LATENCY = Histogram("rag_retrieval_latency_seconds", "Retrieval latency.")
RAG_GENERATION_LATENCY = Histogram("rag_generation_latency_seconds", "Generation latency.")
RAG_EMBEDDING_LATENCY = Histogram("rag_embedding_latency_seconds", "Embedding latency.")
RAG_RERANKING_LATENCY = Histogram("rag_reranking_latency_seconds", "Reranking latency.")
RAG_UPLOAD_PROCESSING_LATENCY = Histogram(
    "rag_upload_processing_latency_seconds",
    "Upload processing latency.",
)
RAG_MULTI_QUERY_LATENCY = Histogram("rag_multi_query_latency_seconds", "Multi-query latency.")
RAG_CACHE_LOOKUP_LATENCY = Histogram(
    "rag_cache_lookup_latency_seconds",
    "Cache lookup latency.",
)

RAG_ACTIVE_SESSIONS = Gauge("rag_active_sessions", "Current active sessions.")
RAG_INDEXED_CHUNKS_TOTAL = Gauge("rag_indexed_chunks_total", "Total indexed chunks.")
RAG_UPLOADED_CHUNKS_TOTAL = Gauge("rag_uploaded_chunks_total", "Total uploaded chunks.")


@contextmanager
def track_latency(histogram: Histogram) -> Iterator[None]:
    started_at = perf_counter()
    try:
        yield
    finally:
        histogram.observe(perf_counter() - started_at)
