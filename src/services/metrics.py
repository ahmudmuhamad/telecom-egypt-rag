from __future__ import annotations

import logging
import socket
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
from typing import Any, Iterator

from prometheus_client import Counter, Gauge, Histogram, REGISTRY, start_http_server

from config.settings import settings


LOGGER = logging.getLogger(__name__)

_METRIC_LOCK = Lock()
_SERVER_LOCK = Lock()
_SERVER_STARTED = False


def _metric_name(name: str) -> str:
    namespace = (settings.rag_metrics_namespace or "").strip().strip("_")
    return f"{namespace}_{name}" if namespace else name


def _registered_collector(name: str) -> Any | None:
    names_to_collectors = getattr(REGISTRY, "_names_to_collectors", {})
    return names_to_collectors.get(name) or names_to_collectors.get(name.removesuffix("_total"))


def _get_or_create(metric_cls: type, name: str, description: str, labels: list[str] | None = None) -> Any:
    full_name = _metric_name(name)
    with _METRIC_LOCK:
        existing = _registered_collector(full_name)
        if existing is not None:
            return existing
        kwargs: dict[str, Any] = {}
        if labels:
            kwargs["labelnames"] = labels
        return metric_cls(full_name, description, **kwargs)


RAG_QUERIES_TOTAL = _get_or_create(
    Counter,
    "queries_total",
    "Total RAG queries handled.",
    ["route", "source_mode", "language"],
)
RAG_ANSWERS_TOTAL = _get_or_create(
    Counter,
    "answers_total",
    "Total RAG answers by final status.",
    ["status"],
)
RAG_ANSWERS_WITH_CITATIONS_TOTAL = _get_or_create(
    Counter,
    "answers_with_citations_total",
    "Total answers that include citations.",
)
RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL = _get_or_create(
    Counter,
    "answers_without_citations_total",
    "Total answers that do not include citations.",
)
RAG_RETRIEVAL_REQUESTS_TOTAL = _get_or_create(
    Counter,
    "retrieval_requests_total",
    "Total retrieval requests by retriever.",
    ["retriever"],
)
RAG_RERANKING_TOTAL = _get_or_create(
    Counter,
    "reranking_total",
    "Total reranking outcomes.",
    ["status"],
)
RAG_FALLBACKS_TOTAL = _get_or_create(
    Counter,
    "fallbacks_total",
    "Total fallback events.",
    ["reason"],
)
RAG_ERRORS_TOTAL = _get_or_create(
    Counter,
    "errors_total",
    "Total RAG errors by stage.",
    ["stage"],
)
RAG_CACHE_HITS_TOTAL = _get_or_create(
    Counter,
    "cache_hits_total",
    "Total cache hits.",
    ["cache_type"],
)
RAG_CACHE_MISSES_TOTAL = _get_or_create(
    Counter,
    "cache_misses_total",
    "Total cache misses.",
    ["cache_type"],
)
RAG_UPLOADS_TOTAL = _get_or_create(
    Counter,
    "uploads_total",
    "Total uploaded files by type and status.",
    ["file_type", "status"],
)
RAG_UPLOADED_CHUNKS_TOTAL = _get_or_create(
    Counter,
    "uploaded_chunks_total",
    "Total uploaded chunks by file type.",
    ["file_type"],
)

RAG_TOTAL_LATENCY = _get_or_create(
    Histogram,
    "total_latency_seconds",
    "End-to-end RAG latency in seconds.",
)
RAG_RETRIEVAL_LATENCY = _get_or_create(
    Histogram,
    "retrieval_latency_seconds",
    "Hybrid retrieval latency in seconds.",
)
RAG_DENSE_RETRIEVAL_LATENCY = _get_or_create(
    Histogram,
    "dense_retrieval_latency_seconds",
    "Dense retrieval latency in seconds.",
)
RAG_BM25_RETRIEVAL_LATENCY = _get_or_create(
    Histogram,
    "bm25_retrieval_latency_seconds",
    "BM25 retrieval latency in seconds.",
)
RAG_RERANKING_LATENCY = _get_or_create(
    Histogram,
    "reranking_latency_seconds",
    "Reranking latency in seconds.",
)
RAG_GENERATION_LATENCY = _get_or_create(
    Histogram,
    "generation_latency_seconds",
    "Model generation latency in seconds.",
)
RAG_CONTEXT_ASSEMBLY_LATENCY = _get_or_create(
    Histogram,
    "context_assembly_latency_seconds",
    "Context assembly latency in seconds.",
)
RAG_UPLOAD_PROCESSING_LATENCY = _get_or_create(
    Histogram,
    "upload_processing_latency_seconds",
    "Uploaded document processing latency in seconds.",
)

RAG_ACTIVE_SESSIONS = _get_or_create(
    Gauge,
    "active_sessions",
    "Current active Streamlit sessions.",
)
RAG_LAST_QUERY_SOURCES_COUNT = _get_or_create(
    Gauge,
    "last_query_sources_count",
    "Number of formatted sources in the last query.",
)
RAG_LAST_QUERY_FINAL_RESULTS_COUNT = _get_or_create(
    Gauge,
    "last_query_final_results_count",
    "Number of final retrieval results in the last query.",
)
RAG_LAST_ANSWER_CITATION_COUNT = _get_or_create(
    Gauge,
    "last_answer_citation_count",
    "Number of citations in the last answer.",
)


def start_metrics_server_once() -> bool:
    global _SERVER_STARTED
    if not settings.enable_prometheus:
        return False

    with _SERVER_LOCK:
        if _SERVER_STARTED:
            return True

        try:
            start_http_server(settings.rag_metrics_port, addr=settings.rag_metrics_host)
        except OSError as exc:
            LOGGER.warning(
                "Prometheus metrics server could not start on %s:%s: %s",
                settings.rag_metrics_host,
                settings.rag_metrics_port,
                exc,
            )
            return False
        except Exception as exc:
            LOGGER.warning("Prometheus metrics server could not start: %s", exc)
            return False

        _SERVER_STARTED = True
        return True


def is_metrics_port_reachable() -> bool:
    try:
        host = "127.0.0.1" if settings.rag_metrics_host in {"0.0.0.0", "::"} else settings.rag_metrics_host
        with socket.create_connection((host, settings.rag_metrics_port), timeout=0.5):
            return True
    except Exception:
        return False


@contextmanager
def track_latency(histogram: Any) -> Iterator[None]:
    started_at = perf_counter()
    try:
        yield
    finally:
        try:
            histogram.observe(perf_counter() - started_at)
        except Exception:
            pass


def _inc(counter: Any, labels: dict[str, str] | None = None) -> None:
    try:
        if labels:
            counter.labels(**labels).inc()
        else:
            counter.inc()
    except Exception:
        pass


def record_query(route: str, source_mode: str, language: str) -> None:
    _inc(
        RAG_QUERIES_TOTAL,
        {
            "route": route or "unknown",
            "source_mode": source_mode or "unknown",
            "language": language or "unknown",
        },
    )


def record_answer(status: str, has_citations: bool) -> None:
    _inc(RAG_ANSWERS_TOTAL, {"status": status or "unknown"})
    if has_citations:
        _inc(RAG_ANSWERS_WITH_CITATIONS_TOTAL)
    else:
        _inc(RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL)


def record_retrieval(retriever: str) -> None:
    _inc(RAG_RETRIEVAL_REQUESTS_TOTAL, {"retriever": retriever or "unknown"})


def record_reranking(status: str) -> None:
    _inc(RAG_RERANKING_TOTAL, {"status": status or "unknown"})


def record_fallback(reason: str) -> None:
    _inc(RAG_FALLBACKS_TOTAL, {"reason": reason or "unknown"})


def record_error(stage: str) -> None:
    _inc(RAG_ERRORS_TOTAL, {"stage": stage or "unknown"})


def record_cache_hit(cache_type: str) -> None:
    _inc(RAG_CACHE_HITS_TOTAL, {"cache_type": cache_type or "unknown"})


def record_cache_miss(cache_type: str) -> None:
    _inc(RAG_CACHE_MISSES_TOTAL, {"cache_type": cache_type or "unknown"})


def record_upload(file_type: str, status: str, chunks_count: int = 0) -> None:
    normalized_file_type = file_type or "unknown"
    _inc(RAG_UPLOADS_TOTAL, {"file_type": normalized_file_type, "status": status or "unknown"})
    if chunks_count > 0:
        try:
            RAG_UPLOADED_CHUNKS_TOTAL.labels(file_type=normalized_file_type).inc(chunks_count)
        except Exception:
            pass


def set_last_query_stats(source_count: int, final_results_count: int, citation_count: int) -> None:
    try:
        RAG_LAST_QUERY_SOURCES_COUNT.set(max(0, int(source_count)))
        RAG_LAST_QUERY_FINAL_RESULTS_COUNT.set(max(0, int(final_results_count)))
        RAG_LAST_ANSWER_CITATION_COUNT.set(max(0, int(citation_count)))
    except Exception:
        pass
