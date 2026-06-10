from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from config.settings import settings
from src.generation.citation_parser import (
    append_sources_section,
    extract_citation_ids,
    validate_answer_grounding,
)
from src.generation.prompt_templates import (
    build_clarification_response,
    build_generation_prompt,
    build_no_source_answer,
    build_rejection_response,
    build_system_prompt,
    detect_response_language,
)
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.source_formatter import (
    clean_user_visible_text,
    format_results_for_generation,
    make_snippet,
)
from src.services.ollama_client import OllamaClient

try:
    from src.logging.rag_logger import RAGLogger
    from src.services.metrics import (
        RAG_CONTEXT_ASSEMBLY_LATENCY,
        RAG_FALLBACKS_TOTAL,
        RAG_GENERATION_LATENCY,
        RAG_TOTAL_LATENCY,
        record_answer,
        record_error,
        record_fallback,
        record_query,
        set_last_query_stats,
        track_latency,
    )
except Exception:  # pragma: no cover
    RAGLogger = None
    RAG_CONTEXT_ASSEMBLY_LATENCY = None
    RAG_FALLBACKS_TOTAL = None
    RAG_GENERATION_LATENCY = None
    RAG_TOTAL_LATENCY = None
    record_answer = None
    record_error = None
    record_fallback = None
    record_query = None
    set_last_query_stats = None
    track_latency = None


class AnswerGenerator:
    def __init__(
        self,
        hybrid_retriever: HybridRetriever | None = None,
        ollama_client: OllamaClient | None = None,
    ) -> None:
        self.retriever = hybrid_retriever or HybridRetriever()
        self.ollama = ollama_client or OllamaClient()
        self.logger = RAGLogger() if RAGLogger is not None else None

    def answer(
        self,
        query: str,
        source_mode: str = "official",
        top_k: int | None = None,
        use_reranking: bool | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        request_started_at = perf_counter()
        language = detect_response_language(query)
        self._log_event("query_received", {"query": query, "source_mode": source_mode, "language": language})
        try:
            retrieval = self.retriever.retrieve(
                query,
                source_mode=source_mode,
                top_k=top_k,
                enable_reranking=use_reranking,
                debug=debug,
            )
        except Exception as exc:
            self._record_error("retrieval")
            self._record_answer("error", False)
            self._log_event(
                "error",
                {
                    "query": query,
                    "source_mode": source_mode,
                    "language": language,
                    "stage": "retrieval",
                    "error": str(exc),
                    "latency_seconds": perf_counter() - request_started_at,
                },
            )
            raise
        route = retrieval.get("route") or {}
        route_type = route.get("route")
        self._record_query(route, source_mode, language)
        self._log_event(
            "retrieval_completed",
            {
                "query": query,
                "route": route_type,
                "source_mode": route.get("source_mode") or source_mode,
                "source_count": len(retrieval.get("final_results") or []),
                "reranking_used": retrieval.get("reranking_used"),
                "latency_seconds": retrieval.get("debug", {}).get("elapsed_seconds"),
            },
        )

        base_response = {
            "query": query,
            "_request_started_at": request_started_at,
            "route": route,
            "language": language,
            "model_used": None,
            "model_tier": None,
            "answer": "",
            "answer_with_sources": "",
            "sources": [],
            "retrieval": retrieval if debug else self._compact_retrieval(retrieval),
            "validation": {
                "valid": True,
                "has_citations": False,
                "invalid_citation_ids": [],
                "reason": "No generation needed.",
            },
            "generation_used": False,
            "fallback_used": False,
            "error": None,
        }

        if route_type == "clarification":
            self._record_fallback("route_clarification")
            return self._finalize(
                base_response,
                build_clarification_response(route, language),
                [],
                status="clarification",
            )
        if route_type == "rejection":
            self._record_fallback("route_rejection")
            return self._finalize(
                base_response,
                build_rejection_response(route, language),
                [],
                status="rejected",
            )

        final_results = retrieval.get("final_results") or []
        if len(final_results) < settings.min_sources_for_answer and not settings.allow_no_source_answer:
            self._record_fallback("no_sources")
            answer = build_no_source_answer(query, language)
            base_response["validation"] = validate_answer_grounding(answer, [], require_citations=False)
            return self._finalize(base_response, answer, [], status="fallback")

        if track_latency is not None and RAG_CONTEXT_ASSEMBLY_LATENCY is not None:
            with track_latency(RAG_CONTEXT_ASSEMBLY_LATENCY):
                sources = format_results_for_generation(
                    final_results,
                    max_sources=settings.generation_max_context_sources,
                    query=query,
                )
        else:
            sources = format_results_for_generation(
                final_results,
                max_sources=settings.generation_max_context_sources,
                query=query,
            )
        if not settings.enable_generation:
            answer = self.build_conservative_answer(query, sources, language)
            base_response["fallback_used"] = True
            base_response["validation"] = validate_answer_grounding(
                answer,
                sources,
                require_citations=settings.generation_require_citations,
            )
            return self._finalize(base_response, answer, sources, status="fallback")

        model_name, model_tier = self.choose_generation_model(route)
        model_sequence = [(model_name, model_tier)]
        if settings.generation_enable_model_fallback:
            model_sequence.extend(self.fallback_model_sequence(model_tier))
        model_sequence = model_sequence[: max(1, settings.generation_max_retries + 1)]

        last_error: str | None = None
        for attempt, (candidate_model, candidate_tier) in enumerate(model_sequence):
            try:
                started_at = perf_counter()
                raw_answer = self._generate_with_model(query, sources, language, candidate_model)
                self._record_generation_latency(perf_counter() - started_at)
                validation = validate_answer_grounding(
                    raw_answer,
                    sources,
                    require_citations=settings.generation_require_citations,
                )
                if validation["valid"]:
                    base_response.update(
                        {
                            "model_used": candidate_model,
                            "model_tier": candidate_tier,
                            "validation": validation,
                            "generation_used": True,
                            "fallback_used": attempt > 0,
                        }
                    )
                    return self._finalize(base_response, raw_answer, sources, status="generated")

                last_error = validation["reason"]
                self._record_fallback("citation_validation_failed")
                self._record_error("validation")
            except Exception as exc:
                last_error = str(exc)
                self._record_fallback("generation_error")
                self._record_error("generation")
                if self._is_generation_endpoint_unavailable(last_error):
                    break

        conservative_answer = self.build_conservative_answer(query, sources, language)
        validation = validate_answer_grounding(
            conservative_answer,
            sources,
            require_citations=settings.generation_require_citations,
        )
        base_response.update(
            {
                "model_used": model_name,
                "model_tier": model_tier,
                "validation": validation,
                "generation_used": False,
                "fallback_used": True,
                "error": last_error,
            }
        )
        return self._finalize(base_response, conservative_answer, sources, status="fallback")

    def choose_generation_model(self, route: dict[str, Any]) -> tuple[str, str]:
        decision = route.get("complexity_decision") or {}
        complexity = str(decision.get("complexity") or "").lower()
        if complexity == "simple":
            return settings.small_generation_model, "small"
        if complexity == "complex":
            return settings.large_generation_model, "large"
        if complexity == "medium":
            return settings.medium_generation_model, "medium"
        model = decision.get("generation_model") or settings.default_generation_model
        if model == settings.small_generation_model:
            return model, "small"
        if model == settings.large_generation_model:
            return model, "large"
        return model, "medium"

    def fallback_model_sequence(self, current_tier: str) -> list[tuple[str, str]]:
        if current_tier == "small":
            return [(settings.medium_generation_model, "medium"), (settings.large_generation_model, "large")]
        if current_tier == "medium":
            return [(settings.large_generation_model, "large")]
        return []

    def build_conservative_answer(
        self,
        query: str,
        sources: list[dict[str, Any]],
        language: str,
    ) -> str:
        if not sources:
            return build_no_source_answer(query, language)

        source = sources[0]
        source_id = source["source_id"]
        metadata = source.get("metadata") or {}
        content = source.get("content") or source.get("snippet") or ""
        clean_content = clean_user_visible_text(str(metadata.get("answer") or content))
        code = self._extract_ussd_code(metadata, content)
        fee = self._extract_fee(metadata, content)
        price = self._extract_price(metadata, content)
        quota = self._extract_quota(metadata, content)
        speed = self._extract_speed(metadata, content)
        package_name = metadata.get("package_name") or source.get("title")
        is_arabic = language in {"ar", "mixed"}

        if self._is_service_code_query(query, content) and code:
            if is_arabic:
                answer = f"كود معرفة الرصيد هو {code}"
                if fee:
                    answer += f"، ورسوم الخدمة {fee}"
                return f"{answer}. [{source_id}]"
            answer = f"You can check your balance by dialing {code}"
            if fee:
                answer += f". The service fee is {fee}"
            return f"{answer}. [{source_id}]"

        faq_answer = clean_user_visible_text(str(metadata.get("answer") or ""))
        if faq_answer:
            return f"{make_snippet(faq_answer, max_chars=320)} [{source_id}]"

        if package_name and any(value for value in (price, quota, speed)):
            details: list[str] = []
            if quota:
                details.append(f"السعة {quota}" if is_arabic else f"quota {quota}")
            if speed:
                details.append(f"السرعة {speed}" if is_arabic else f"speed {speed}")
            if price:
                details.append(f"السعر {price}" if is_arabic else f"price {price}")
            return f"{package_name}: " + "، ".join(details) + f". [{source_id}]"

        snippet = make_snippet(clean_content, max_chars=420)
        if is_arabic:
            return f"المعلومة المتاحة من المصدر الرسمي هي: {snippet}. [{source_id}]"
        return f"The available official source says: {snippet}. [{source_id}]"

    def _is_service_code_query(self, query: str, content: str) -> bool:
        normalized = f"{query} {content}".lower()
        return any(term in normalized for term in ("code", "balance", "كود", "رصيد"))

    def _extract_ussd_code(self, metadata: dict[str, Any], content: str) -> str | None:
        for key in ("subscription_code", "ussd_codes"):
            value = metadata.get(key)
            if isinstance(value, list) and value:
                return str(value[0]).replace(" ", "")
            if isinstance(value, str) and value.strip():
                return value.strip().replace(" ", "")
        matches = re.findall(r"\*\s*\d+(?:\s*\*\s*[\w\u0600-\u06FF]+)*\s*#?", content or "")
        if matches:
            return re.sub(r"\s+", "", matches[0])
        return None

    def _extract_fee(self, metadata: dict[str, Any], content: str) -> str | None:
        for key in ("fee", "fees", "service_fee"):
            value = metadata.get(key)
            if value:
                return clean_user_visible_text(str(value))
        match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:قروش|قرش|pt|PT|p\.?t\.?)", content or "")
        return match.group(0) if match else None

    def _extract_price(self, metadata: dict[str, Any], content: str) -> str | None:
        for key in ("price", "price_egp", "monthly_fee", "monthly_fee_egp", "yearly_fee", "yearly_fee_egp"):
            value = metadata.get(key)
            if value:
                if isinstance(value, int | float):
                    return f"{value:g} EGP"
                return clean_user_visible_text(str(value))
        match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:EGP|LE|جنيه)", content or "", flags=re.IGNORECASE)
        return match.group(0) if match else None

    def _extract_quota(self, metadata: dict[str, Any], content: str) -> str | None:
        for key in ("quota", "quota_gb"):
            value = metadata.get(key)
            if value:
                return f"{value} GB" if key == "quota_gb" and str(value).isdigit() else str(value)
        match = re.search(r"\d[\d,]*(?:\.\d+)?\s*GB", content or "", flags=re.IGNORECASE)
        return match.group(0) if match else None

    def _extract_speed(self, metadata: dict[str, Any], content: str) -> str | None:
        value = metadata.get("speed")
        if value:
            return str(value)
        match = re.search(r"(?:up to\s*)?\d[\d,]*(?:\.\d+)?\s*Mbps", content or "", flags=re.IGNORECASE)
        return match.group(0) if match else None

    def _generate_with_model(
        self,
        query: str,
        sources: list[dict[str, Any]],
        language: str,
        model: str,
    ) -> str:
        system_prompt = build_system_prompt(language)
        prompt = build_generation_prompt(query, sources, language)
        return self.ollama.generate(
            prompt=prompt,
            system=system_prompt,
            temperature=settings.generation_temperature,
            model=model,
        )

    def _is_generation_endpoint_unavailable(self, error: str) -> bool:
        normalized = (error or "").lower()
        return any(
            marker in normalized
            for marker in (
                "connection refused",
                "connecterror",
                "404 not found",
                "/api/generate",
                "/api/chat",
            )
        )

    def _finalize(
        self,
        response: dict[str, Any],
        answer: str,
        sources: list[dict[str, Any]],
        status: str,
    ) -> dict[str, Any]:
        response["answer"] = answer
        response["sources"] = sources
        response["answer_with_sources"] = append_sources_section(answer, sources) if sources else answer
        citation_count = len(extract_citation_ids(answer))
        final_results_count = len((response.get("retrieval") or {}).get("final_results") or [])
        self._record_answer(status, bool(citation_count))
        self._record_last_query_stats(len(sources), final_results_count, citation_count)
        self._record_total_latency(response)
        response.pop("_request_started_at", None)
        self._log_answer(response, status=status, citation_count=citation_count)
        return response

    def _compact_retrieval(self, retrieval: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": retrieval.get("query"),
            "route": retrieval.get("route"),
            "final_results": retrieval.get("final_results"),
            "reranking_enabled": retrieval.get("reranking_enabled"),
            "reranking_used": retrieval.get("reranking_used"),
            "reranking_error": retrieval.get("reranking_error"),
        }

    def _record_generation_latency(self, elapsed_seconds: float) -> None:
        if RAG_GENERATION_LATENCY is None:
            return
        try:
            RAG_GENERATION_LATENCY.observe(elapsed_seconds)
        except Exception:
            pass

    def _record_fallback(self, reason: str) -> None:
        if record_fallback is not None:
            try:
                record_fallback(reason)
            except Exception:
                pass
        elif RAG_FALLBACKS_TOTAL is None:
            return
        else:
            try:
                RAG_FALLBACKS_TOTAL.labels(reason=reason).inc()
            except Exception:
                pass
        self._log_event("fallback_used", {"reason": reason})

    def _record_query(self, route: dict[str, Any], source_mode: str, language: str) -> None:
        if record_query is None:
            return
        try:
            record_query(
                route=str(route.get("route") or "unknown"),
                source_mode=str(route.get("source_mode") or source_mode or "unknown"),
                language=str(route.get("language_hint") or language or "unknown"),
            )
        except Exception:
            pass

    def _record_answer(self, status: str, has_citations: bool) -> None:
        if record_answer is None:
            return
        try:
            record_answer(status, has_citations)
        except Exception:
            pass

    def _record_error(self, stage: str) -> None:
        if record_error is None:
            return
        try:
            record_error(stage)
        except Exception:
            pass

    def _record_last_query_stats(
        self,
        source_count: int,
        final_results_count: int,
        citation_count: int,
    ) -> None:
        if set_last_query_stats is None:
            return
        try:
            set_last_query_stats(source_count, final_results_count, citation_count)
        except Exception:
            pass

    def _record_total_latency(self, response: dict[str, Any]) -> None:
        if RAG_TOTAL_LATENCY is None:
            return
        started_at = response.get("_request_started_at")
        if started_at is None:
            return
        try:
            RAG_TOTAL_LATENCY.observe(perf_counter() - float(started_at))
        except Exception:
            pass

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.logger is None:
            return
        try:
            self.logger.log_event(event_type, payload)
        except Exception:
            pass

    def _log_answer(self, response: dict[str, Any], status: str, citation_count: int) -> None:
        if self.logger is None:
            return
        try:
            self.logger.log_event(
                "generation_completed",
                {
                    "query": response.get("query"),
                    "route": response.get("route", {}).get("route"),
                    "source_count": len(response.get("sources") or []),
                    "generation_used": response.get("generation_used"),
                    "fallback_used": response.get("fallback_used"),
                    "answer_status": status,
                    "citation_count": citation_count,
                    "error": response.get("error"),
                },
            )
            self.logger.log_query(
                {
                    "query": response.get("query"),
                    "route": response.get("route", {}).get("route"),
                    "model_used": response.get("model_used"),
                    "model_tier": response.get("model_tier"),
                    "source_count": len(response.get("sources") or []),
                    "validation": response.get("validation"),
                    "fallback_used": response.get("fallback_used"),
                    "generation_used": response.get("generation_used"),
                    "error": response.get("error"),
                }
            )
        except Exception:
            pass

    def generate(self, query: str) -> str:
        return self.answer(query)["answer_with_sources"]
