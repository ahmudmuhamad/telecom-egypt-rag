from __future__ import annotations

from time import perf_counter
from typing import Any

from config.settings import settings
from src.generation.citation_parser import append_sources_section, validate_answer_grounding
from src.generation.prompt_templates import (
    build_clarification_response,
    build_generation_prompt,
    build_no_source_answer,
    build_rejection_response,
    build_system_prompt,
    detect_response_language,
)
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.source_formatter import format_results_for_generation, make_snippet
from src.services.ollama_client import OllamaClient

try:
    from src.logging.rag_logger import RAGLogger
    from src.services.metrics import (
        RAG_ANSWERS_WITH_CITATIONS_TOTAL,
        RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL,
        RAG_FALLBACKS_TOTAL,
        RAG_GENERATION_LATENCY,
    )
except Exception:  # pragma: no cover
    RAGLogger = None
    RAG_ANSWERS_WITH_CITATIONS_TOTAL = None
    RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL = None
    RAG_FALLBACKS_TOTAL = None
    RAG_GENERATION_LATENCY = None


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
        language = detect_response_language(query)
        retrieval = self.retriever.retrieve(
            query,
            source_mode=source_mode,
            top_k=top_k,
            enable_reranking=use_reranking,
            debug=debug,
        )
        route = retrieval.get("route") or {}
        route_type = route.get("route")

        base_response = {
            "query": query,
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
            answer = build_clarification_response(route, language)
            return self._finalize(base_response, answer, [])
        if route_type == "rejection":
            self._record_fallback("route_rejection")
            answer = build_rejection_response(route, language)
            return self._finalize(base_response, answer, [])

        final_results = retrieval.get("final_results") or []
        if len(final_results) < settings.min_sources_for_answer and not settings.allow_no_source_answer:
            self._record_fallback("no_sources")
            answer = build_no_source_answer(query, language)
            base_response["validation"] = validate_answer_grounding(
                answer,
                [],
                require_citations=False,
            )
            return self._finalize(base_response, answer, [])

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
            return self._finalize(base_response, answer, sources)

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
                    self._record_answer_citation_metric(validation)
                    return self._finalize(base_response, raw_answer, sources)

                last_error = validation["reason"]
                self._record_fallback("citation_validation_failed")
            except Exception as exc:
                last_error = str(exc)
                self._record_fallback("generation_error")
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
        self._record_answer_citation_metric(validation)
        return self._finalize(base_response, conservative_answer, sources)

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
        snippet = make_snippet(source.get("content") or source.get("snippet") or "", max_chars=700)
        if language in {"ar", "mixed"}:
            return f"وفقًا للمصدر الرسمي المسترجع، المعلومة ذات الصلة هي: {snippet} [{source['source_id']}]"
        return f"Based on the retrieved official source, the relevant information is: {snippet} [{source['source_id']}]"

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
    ) -> dict[str, Any]:
        response["answer"] = answer
        response["sources"] = sources
        response["answer_with_sources"] = append_sources_section(answer, sources) if sources else answer
        self._log_answer(response)
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

    def _record_answer_citation_metric(self, validation: dict[str, Any]) -> None:
        try:
            if validation.get("has_citations") and RAG_ANSWERS_WITH_CITATIONS_TOTAL is not None:
                RAG_ANSWERS_WITH_CITATIONS_TOTAL.inc()
            elif RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL is not None:
                RAG_ANSWERS_WITHOUT_CITATIONS_TOTAL.inc()
        except Exception:
            pass

    def _record_fallback(self, reason: str) -> None:
        if RAG_FALLBACKS_TOTAL is None:
            return
        try:
            RAG_FALLBACKS_TOTAL.labels(reason=reason).inc()
        except Exception:
            pass

    def _log_answer(self, response: dict[str, Any]) -> None:
        if self.logger is None:
            return
        try:
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
