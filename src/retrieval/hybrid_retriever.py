from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from config.settings import settings
from src.retrieval.bm25_retriever import BM25Retriever, UploadedBM25Retriever
from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.query_router import route_query
from src.retrieval.reranker import Reranker
from src.retrieval.result_utils import rerank_results

try:
    from src.logging.rag_logger import RAGLogger
    from src.services.metrics import (
        RAG_RERANKING_LATENCY,
        RAG_RETRIEVAL_LATENCY,
        record_error,
        record_fallback,
        record_reranking,
        record_retrieval,
    )
except Exception:  # pragma: no cover
    RAGLogger = None
    RAG_RERANKING_LATENCY = None
    RAG_RETRIEVAL_LATENCY = None
    record_error = None
    record_fallback = None
    record_reranking = None
    record_retrieval = None


ARABIC_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")

CODE_TERMS = ("code", "*", "#", "\u0643\u0648\u062f", "balance", "\u0631\u0635\u064a\u062f")
PRICE_TERMS = (
    "price",
    "cost",
    "fee",
    "egp",
    "\u0633\u0639\u0631",
    "\u062a\u0643\u0644\u0641\u0629",
    "\u0631\u0633\u0648\u0645",
    "\u0643\u0627\u0645",
    "\u062c\u0646\u064a\u0647",
)
WE_HOME_TERMS = (
    "we space",
    "we air",
    "we sonic",
    "we life",
    "super",
    "mega",
    "ultra",
    "max",
    "gb",
    "internet",
    "\u062c\u064a\u062c\u0627",
    "\u0627\u0646\u062a\u0631\u0646\u062a",
    "\u0646\u062a",
)
DEVICE_TERMS = (
    "router",
    "\u0631\u0627\u0648\u062a\u0631",
    "device",
    "iphone",
    "samsung",
    "tp-link",
    "zte",
    "huawei",
    "\u0645\u0648\u0628\u0627\u064a\u0644",
    "\u0647\u0627\u062a\u0641",
)
HOTLINE_TERMS = (
    "customer service",
    "call center",
    "hotline",
    "\u062e\u062f\u0645\u0629 \u0627\u0644\u0639\u0645\u0644\u0627\u0621",
)


class HybridRetriever:
    def __init__(
        self,
        dense_retriever: DenseRetriever | None = None,
        bm25_retriever: BM25Retriever | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.dense = dense_retriever or DenseRetriever()
        self.bm25 = bm25_retriever or BM25Retriever()
        self.reranker = reranker or Reranker()
        self.logger = RAGLogger() if RAGLogger is not None else None

    def retrieve(
        self,
        query: str,
        source_mode: str = "official",
        upload_session_id: str | None = None,
        top_k: int | None = None,
        enable_reranking: bool | None = None,
        rerank_top_k: int | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        route = route_query(query, source_mode=source_mode)
        self._record_retrieval("hybrid")

        response: dict[str, Any] = {
            "query": query,
            "route": route,
            "upload_session_id": upload_session_id if route.get("source_mode") != "official" else None,
            "dense_results": [],
            "bm25_results": [],
            "fused_results": [],
            "boosted_results": [],
            "reranked_results": [],
            "final_results": [],
            "reranking_enabled": self._reranking_enabled(enable_reranking),
            "reranking_used": False,
            "reranking_error": None,
            "debug": {},
        }
        if route["route"] != "retrieval":
            self._log_retrieval(query, response, perf_counter() - started_at)
            return response

        if route["source_mode"] in {"uploads", "both"} and not upload_session_id:
            response["debug"]["message"] = "No upload session was provided."
            self._log_retrieval(query, response, perf_counter() - started_at)
            return response

        dense_top_k, bm25_top_k, candidate_top_k, final_top_k = self._top_k_from_route(
            route,
            top_k,
            rerank_top_k,
        )
        source_mode = route["source_mode"]
        dense_results, bm25_results, fused_results = self._retrieve_for_source_mode(
            query=query,
            source_mode=source_mode,
            route_filters=route.get("metadata_filters") or {},
            upload_session_id=upload_session_id,
            dense_top_k=dense_top_k,
            bm25_top_k=bm25_top_k,
        )
        boosted_results = self.apply_metadata_boosts(query, fused_results)
        candidates = boosted_results[:candidate_top_k]
        reranked_results: list[dict[str, Any]] = []
        final_results: list[dict[str, Any]]
        if response["reranking_enabled"]:
            rerank_started_at = perf_counter()
            original_enabled = self.reranker.enabled
            try:
                if self.reranker.last_error and self.reranker.model is None and not self.reranker.enabled:
                    response["reranking_error"] = self.reranker.last_error
                    self._record_fallback("reranker_unavailable")
                    self._record_reranking("failed")
                    final_results = self._mark_unreranked(boosted_results[:final_top_k])
                    reranked_results = []
                else:
                    self.reranker.enabled = True
                    reranked_results = self.reranker.rerank(query, candidates, top_k=final_top_k)
                    final_results = reranked_results
                response["reranking_used"] = bool(
                    reranked_results
                    and any(result.get("reranker_score") is not None for result in reranked_results)
                )
                if response["reranking_used"]:
                    final_results = reranked_results
                else:
                    response["reranking_error"] = response["reranking_error"] or self.reranker.last_error
                    if response["reranking_error"]:
                        self._record_fallback("reranker_unavailable")
                        self._record_reranking("failed")
                    else:
                        self._record_reranking("disabled")
                    final_results = self._mark_unreranked(boosted_results[:final_top_k])
                    reranked_results = []
            except Exception as exc:
                if self.reranker.strict_mode:
                    raise
                response["reranking_error"] = str(exc)
                self._record_fallback("reranker_error")
                self._record_error("reranking")
                self._record_reranking("failed")
                final_results = self._mark_unreranked(boosted_results[:final_top_k])
            finally:
                if (
                    enable_reranking is not None
                    and not (self.reranker.last_error and self.reranker.model is None)
                ):
                    self.reranker.enabled = original_enabled
                self._record_reranking_latency(perf_counter() - rerank_started_at)
            if response["reranking_used"]:
                self._record_reranking("used")
        else:
            self._record_reranking("disabled")
            final_results = self._mark_unreranked(boosted_results[:final_top_k])

        response.update(
            {
                "dense_results": dense_results,
                "bm25_results": bm25_results,
                "fused_results": fused_results,
                "boosted_results": boosted_results,
                "reranked_results": reranked_results,
                "final_results": final_results,
            }
        )
        if debug:
            response["debug"].update(
                {
                    "dense_top_k": dense_top_k,
                    "bm25_top_k": bm25_top_k,
                    "rerank_top_k": candidate_top_k,
                    "final_top_k": final_top_k,
                    "rrf_k": settings.rrf_k,
                    "metadata_filters": route.get("metadata_filters") or {},
                    "reranker_model": self.reranker.loaded_model_name or self.reranker.model_name,
                    "reranker_device": self.reranker.device,
                    "reranking_enabled": response["reranking_enabled"],
                    "reranking_used": response["reranking_used"],
                    "reranking_error": response["reranking_error"],
                    "elapsed_seconds": perf_counter() - started_at,
                }
            )
        self._log_retrieval(query, response, perf_counter() - started_at)
        return response

    def rrf_fusion(
        self,
        dense_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        k: int = 60,
    ) -> list[dict[str, Any]]:
        fused: dict[str, dict[str, Any]] = {}
        for retriever_name, results in (("dense", dense_results), ("bm25", bm25_results)):
            for rank, result in enumerate(results, start=1):
                key = result.get("chunk_id") or f"{result.get('citation_url')}:{result.get('title')}"
                if key not in fused:
                    fused[key] = dict(result)
                    fused[key]["retriever"] = "hybrid"
                    fused[key]["score"] = 0.0
                    fused[key]["rrf_score"] = 0.0
                    fused[key]["boost_score"] = 0.0
                    fused[key]["final_score"] = 0.0
                fused[key]["rrf_score"] += 1.0 / (k + rank)
                fused[key]["score"] = fused[key]["rrf_score"]
                if retriever_name == "dense":
                    fused[key]["dense_score"] = result.get("dense_score", result.get("score"))
                else:
                    fused[key]["bm25_score"] = result.get("bm25_score", result.get("score"))

        sorted_results = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
        for result in sorted_results:
            result["final_score"] = result["rrf_score"]
        return rerank_results(sorted_results)

    def rrf_fusion_many(
        self,
        result_sets: list[tuple[str, list[dict[str, Any]]]],
        k: int = 60,
    ) -> list[dict[str, Any]]:
        fused: dict[str, dict[str, Any]] = {}
        for retriever_name, results in result_sets:
            for rank, result in enumerate(results, start=1):
                key = result.get("chunk_id") or f"{result.get('citation_url')}:{result.get('title')}"
                if key not in fused:
                    fused[key] = dict(result)
                    fused[key]["retriever"] = "hybrid"
                    fused[key]["score"] = 0.0
                    fused[key]["rrf_score"] = 0.0
                    fused[key]["boost_score"] = 0.0
                    fused[key]["final_score"] = 0.0
                fused[key]["rrf_score"] += 1.0 / (k + rank)
                fused[key]["score"] = fused[key]["rrf_score"]
                fused[key][f"{retriever_name}_score"] = result.get("score")
        sorted_results = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
        for result in sorted_results:
            result["final_score"] = result["rrf_score"]
        return rerank_results(sorted_results)

    def _retrieve_for_source_mode(
        self,
        query: str,
        source_mode: str,
        route_filters: dict[str, Any],
        upload_session_id: str | None,
        dense_top_k: int,
        bm25_top_k: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if source_mode == "both":
            official_filters = self._source_filters("official", route_filters, upload_session_id)
            upload_filters = self._source_filters("uploads", {}, upload_session_id)
            official_dense = self.dense.search(
                query,
                top_k=settings.both_official_top_k,
                filters=official_filters,
            )
            official_bm25 = self.bm25.search(
                query,
                top_k=settings.both_official_top_k,
                filters=official_filters,
            )
            upload_dense = self.dense.search(
                query,
                top_k=settings.both_upload_top_k,
                filters=upload_filters,
            )
            upload_bm25 = UploadedBM25Retriever(upload_session_id or "").search(
                query,
                top_k=settings.both_upload_top_k,
                filters=upload_filters,
            )
            dense_results = [*official_dense, *upload_dense]
            bm25_results = [*official_bm25, *upload_bm25]
            fused_results = self.rrf_fusion_many(
                [
                    ("official_dense", official_dense),
                    ("official_bm25", official_bm25),
                    ("upload_dense", upload_dense),
                    ("upload_bm25", upload_bm25),
                ],
                k=settings.rrf_k,
            )
            return dense_results, bm25_results, fused_results

        filters = self._source_filters(source_mode, route_filters, upload_session_id)
        dense_results = self.dense.search(query, top_k=dense_top_k, filters=filters)
        if source_mode == "uploads":
            bm25_results = UploadedBM25Retriever(upload_session_id or "").search(
                query,
                top_k=bm25_top_k,
                filters=filters,
            )
        else:
            bm25_results = self.bm25.search(query, top_k=bm25_top_k, filters=filters)
            if route_filters and not dense_results and not bm25_results:
                fallback_filters = self._source_filters(source_mode, {}, upload_session_id)
                dense_results = self.dense.search(query, top_k=dense_top_k, filters=fallback_filters)
                bm25_results = self.bm25.search(query, top_k=bm25_top_k, filters=fallback_filters)
        return dense_results, bm25_results, self.rrf_fusion(dense_results, bm25_results, k=settings.rrf_k)

    def _source_filters(
        self,
        source_mode: str,
        route_filters: dict[str, Any],
        upload_session_id: str | None,
    ) -> dict[str, Any]:
        filters = dict(route_filters or {})
        if source_mode == "official":
            filters["source_type"] = "official_website"
        elif source_mode == "uploads":
            filters["source_type"] = "user_upload"
            filters["upload_session_id"] = upload_session_id
        return {key: value for key, value in filters.items() if value not in (None, "", [])}

    def apply_metadata_boosts(
        self,
        query: str,
        results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_query = self.normalize_query_for_matching(query)
        entity_tokens = self.extract_query_entity_tokens(query)
        boosted: list[dict[str, Any]] = []
        for result in results:
            item = dict(result)
            metadata = item.get("metadata") or {}
            content = self.normalize_query_for_matching(
                " ".join(
                    str(part or "")
                    for part in (item.get("title"), item.get("content"), item.get("index_text"))
                )
            )
            record_type = str(item.get("record_type") or "").lower()
            category = str(item.get("category") or "").lower()
            boost = 0.0
            if entity_tokens:
                raw_content = " ".join(
                    str(part or "")
                    for part in (
                        item.get("title"),
                        item.get("content"),
                        item.get("index_text"),
                        metadata.get("product_name"),
                        metadata.get("brand"),
                        metadata.get("model"),
                        " ".join(str(alias) for alias in metadata.get("search_aliases") or []),
                    )
                ).lower()
                title_text = str(item.get("title") or "").lower()
                entity_matches = sum(1 for token in entity_tokens if token.lower() in raw_content)
                title_matches = sum(1 for token in entity_tokens if token.lower() in title_text)
                if entity_matches:
                    boost += min(0.18, 0.05 * entity_matches)
                if title_matches == len(entity_tokens):
                    boost += 0.12
                if category == "devices":
                    boost += 0.08

            if item.get("source_type") == "user_upload":
                query_tokens = {
                    token
                    for token in re.findall(r"[\w\u0600-\u06FF-]+", normalized_query)
                    if len(token) > 2
                }
                if any(token in content for token in query_tokens):
                    boost += 0.06
                if any(token in content for token in query_tokens if any(char.isdigit() for char in token)):
                    boost += 0.04

            if any(term in normalized_query for term in CODE_TERMS):
                if any(kind in record_type for kind in ("service_code", "service_detail", "service_fee")):
                    boost += 0.05
                if metadata.get("subscription_code") or metadata.get("ussd_codes"):
                    boost += 0.04
                if "*" in content or "#" in content:
                    boost += 0.03

            price_query = any(term in normalized_query for term in PRICE_TERMS)
            if price_query:
                if any(
                    metadata.get(key) is not None
                    for key in (
                        "price_egp",
                        "price_numeric",
                        "monthly_fee_egp",
                        "yearly_fee_egp",
                        "fee",
                    )
                ):
                    boost += 0.05
                if any(term in content for term in ("egp", "le", "\u062c\u0646\u064a\u0647", "\u0642\u0631\u0648\u0634")):
                    boost += 0.03

            if any(term in normalized_query for term in WE_HOME_TERMS):
                if category == "we_home":
                    boost += 0.04
                if record_type in {"package", "yearly_package", "add_on"}:
                    boost += 0.04
                if metadata.get("product_family"):
                    boost += 0.02
                tier = str(metadata.get("tier") or "").lower()
                if tier and tier in normalized_query:
                    boost += 0.04
                if ("gb" in normalized_query or "\u062c\u064a\u062c\u0627" in normalized_query) and (
                    metadata.get("quota") or metadata.get("quota_gb")
                ):
                    boost += 0.03
                if "speed" in normalized_query and metadata.get("speed"):
                    boost += 0.02

            if any(term in normalized_query for term in DEVICE_TERMS):
                if category == "devices":
                    boost += 0.05
                for key in ("brand", "product_name"):
                    value = self.normalize_query_for_matching(str(metadata.get(key) or ""))
                    if value and value in normalized_query:
                        boost += 0.04
                if metadata.get("device_category"):
                    boost += 0.02
                if price_query and metadata.get("price_numeric") is not None:
                    boost += 0.03

            if any(term in normalized_query for term in HOTLINE_TERMS):
                if "111" in content:
                    boost += 0.08
                if category == "faq":
                    boost += 0.02

            boost += self._language_boost(normalized_query, item)
            item["boost_score"] = round(min(boost, 0.35), 6)
            item["final_score"] = float(item.get("rrf_score") or 0.0) + item["boost_score"]
            boosted.append(item)

        boosted.sort(key=lambda item: item["final_score"], reverse=True)
        return rerank_results(boosted)

    def normalize_query_for_matching(self, query: str) -> str:
        normalized = (query or "").translate(ARABIC_DIGITS).lower()
        normalized = re.sub(r"[\u0622\u0623\u0625]", "\u0627", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def extract_query_entity_tokens(self, query: str) -> list[str]:
        tokens: list[str] = []
        for match in re.findall(r"\b[A-Z][A-Za-z0-9-]{2,}\b", query or ""):
            tokens.append(match)
        for match in re.findall(
            r"\b(?=[A-Za-z0-9-]*[A-Za-z])(?=[A-Za-z0-9-]*\d)[A-Za-z0-9-]{3,}\b",
            query or "",
        ):
            tokens.append(match)
        for token in ("DEX", "Cordless", "D1005", "VN020", "ZXHN", "Huawei", "ZTE", "TP-Link"):
            if token.lower() in (query or "").lower():
                tokens.append(token)
        seen: set[str] = set()
        output: list[str] = []
        for token in tokens:
            key = token.lower()
            if key not in seen:
                seen.add(key)
                output.append(token)
        return output

    def _top_k_from_route(
        self,
        route: dict[str, Any],
        top_k: int | None,
        rerank_top_k: int | None,
    ) -> tuple[int, int, int, int]:
        source_mode = route.get("source_mode")
        if source_mode == "uploads":
            dense_top_k = settings.upload_dense_top_k
            bm25_top_k = settings.upload_bm25_top_k
            candidate_top_k = max(settings.upload_dense_top_k, settings.upload_bm25_top_k)
            final_top_k = settings.upload_final_top_k
        elif source_mode == "both":
            dense_top_k = max(settings.standard_dense_top_k, settings.upload_dense_top_k)
            bm25_top_k = max(settings.standard_bm25_top_k, settings.upload_bm25_top_k)
            candidate_top_k = settings.both_final_top_k * 3
            final_top_k = settings.both_final_top_k
        else:
            decision = route.get("complexity_decision") or {}
            dense_top_k = int(decision.get("dense_top_k") or settings.dense_top_k)
            bm25_top_k = int(decision.get("bm25_top_k") or settings.bm25_top_k)
            candidate_top_k = int(decision.get("rerank_top_k") or settings.rerank_top_k)
            final_top_k = int(decision.get("final_top_k") or settings.final_top_k)
        if rerank_top_k is not None:
            candidate_top_k = rerank_top_k
        if top_k is not None:
            final_top_k = top_k
        candidate_top_k = max(candidate_top_k, final_top_k)
        return dense_top_k, bm25_top_k, candidate_top_k, final_top_k

    def _language_boost(self, normalized_query: str, result: dict[str, Any]) -> float:
        has_arabic = bool(re.search(r"[\u0600-\u06FF]", normalized_query))
        has_latin = bool(re.search(r"[a-z]", normalized_query))
        language = str(result.get("language") or "").lower()
        if has_arabic and language == "ar":
            return 0.01
        if has_latin and not has_arabic and language == "en":
            return 0.01
        return 0.0

    def _record_retrieval(self, retriever: str) -> None:
        if record_retrieval is None:
            return
        try:
            record_retrieval(retriever)
        except Exception:
            pass

    def _reranking_enabled(self, override: bool | None) -> bool:
        return self.reranker.is_enabled() if override is None else bool(override)

    def _record_reranking_latency(self, elapsed_seconds: float) -> None:
        if RAG_RERANKING_LATENCY is None:
            return
        try:
            RAG_RERANKING_LATENCY.observe(elapsed_seconds)
        except Exception:
            pass

    def _record_fallback(self, reason: str) -> None:
        if record_fallback is None:
            return
        try:
            record_fallback(reason)
        except Exception:
            pass

    def _record_reranking(self, status: str) -> None:
        if record_reranking is None:
            return
        try:
            record_reranking(status)
        except Exception:
            pass

    def _record_error(self, stage: str) -> None:
        if record_error is None:
            return
        try:
            record_error(stage)
        except Exception:
            pass

    def _mark_unreranked(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output = rerank_results([dict(result) for result in results])
        for result in output:
            result.setdefault("reranker_score", None)
            result.setdefault("pre_rerank_rank", result.get("rank"))
            result.setdefault("pre_rerank_score", result.get("final_score"))
            result.setdefault("reranker_model", None)
        return output

    def _log_retrieval(
        self,
        query: str,
        response: dict[str, Any],
        elapsed_seconds: float,
    ) -> None:
        if RAG_RETRIEVAL_LATENCY is not None:
            try:
                RAG_RETRIEVAL_LATENCY.observe(elapsed_seconds)
            except Exception:
                pass
        if self.logger is None:
            return
        try:
            self.logger.log_query(
                {
                    "query": query,
                    "route": response["route"].get("route"),
                    "source_mode": response["route"].get("source_mode"),
                    "reranking_used": response.get("reranking_used"),
                    "reranking_error": response.get("reranking_error"),
                    "reranker_model": self.reranker.loaded_model_name or self.reranker.model_name,
                    "candidate_count": len(response.get("boosted_results") or []),
                    "final_count": len(response.get("final_results") or []),
                    "elapsed_seconds": elapsed_seconds,
                }
            )
        except Exception:
            pass
