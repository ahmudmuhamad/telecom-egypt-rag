from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.settings import settings


class QueryComplexity(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class PipelineMode(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass(frozen=True)
class ModelRoutingDecision:
    complexity: QueryComplexity
    pipeline_mode: PipelineMode
    generation_model: str
    use_multi_query: bool
    use_reranker: bool
    use_context_compression: bool
    dense_top_k: int
    bm25_top_k: int
    rerank_top_k: int
    final_top_k: int
    reason: str


SIMPLE_TERMS = {
    "code",
    "cost",
    "fee",
    "number",
    "quota",
    "speed",
    "validity",
    "price",
    "balance",
    "sim swap",
}
MEDIUM_TERMS = {
    "list",
    "how",
    "subscribe",
    "terms",
    "available",
    "packages",
    "addons",
    "add-ons",
    "requirements",
}
COMPLEX_TERMS = {
    "compare",
    "comparison",
    "recommend",
    "better",
    "summarize",
    "summary",
    "analyze",
    "analysis",
    "gaming",
    "uploaded",
    "pdf",
}


def _fast_decision(reason: str) -> ModelRoutingDecision:
    return ModelRoutingDecision(
        complexity=QueryComplexity.SIMPLE,
        pipeline_mode=PipelineMode.FAST,
        generation_model=settings.small_generation_model,
        use_multi_query=False,
        use_reranker=settings.enable_reranking,
        use_context_compression=False,
        dense_top_k=settings.fast_dense_top_k,
        bm25_top_k=settings.fast_bm25_top_k,
        rerank_top_k=settings.fast_rerank_top_k,
        final_top_k=settings.fast_final_top_k,
        reason=reason,
    )


def _standard_decision(reason: str) -> ModelRoutingDecision:
    return ModelRoutingDecision(
        complexity=QueryComplexity.MEDIUM,
        pipeline_mode=PipelineMode.STANDARD,
        generation_model=settings.medium_generation_model,
        use_multi_query=settings.enable_multi_query,
        use_reranker=settings.enable_reranking,
        use_context_compression=False,
        dense_top_k=settings.standard_dense_top_k,
        bm25_top_k=settings.standard_bm25_top_k,
        rerank_top_k=settings.standard_rerank_top_k,
        final_top_k=settings.standard_final_top_k,
        reason=reason,
    )


def _deep_decision(reason: str) -> ModelRoutingDecision:
    return ModelRoutingDecision(
        complexity=QueryComplexity.COMPLEX,
        pipeline_mode=PipelineMode.DEEP,
        generation_model=settings.large_generation_model,
        use_multi_query=settings.enable_multi_query,
        use_reranker=settings.enable_reranking,
        use_context_compression=settings.enable_context_compression,
        dense_top_k=settings.deep_dense_top_k,
        bm25_top_k=settings.deep_bm25_top_k,
        rerank_top_k=settings.deep_rerank_top_k,
        final_top_k=settings.deep_final_top_k,
        reason=reason,
    )


def classify_query_complexity_rule_based(
    query: str,
    source_mode: str = "official",
) -> ModelRoutingDecision:
    """Classify query complexity with simple domain rules.

    This is rule-based for now because the Telecom Egypt domain is narrow and
    predictable. LLM-based routing can be added later, and model fallback will
    be added after generation quality validation.
    """

    normalized = query.lower().strip()
    words = normalized.split()

    if source_mode.lower() in {"uploaded", "mixed", "official_and_uploaded"}:
        return _deep_decision("Uploaded or mixed source mode needs deeper retrieval.")

    if len(words) >= 18:
        return _deep_decision("Long query likely needs comparison, synthesis, or analysis.")

    if any(term in normalized for term in COMPLEX_TERMS):
        return _deep_decision("Query contains complex reasoning or comparison terms.")

    if any(term in normalized for term in MEDIUM_TERMS):
        return _standard_decision("Query asks for steps, lists, terms, or requirements.")

    if len(words) <= 8 or any(term in normalized for term in SIMPLE_TERMS):
        return _fast_decision("Short factual query or simple telecom attribute lookup.")

    return _standard_decision("Defaulting to standard RAG path for normal support query.")


if __name__ == "__main__":
    examples = [
        "What is the SIM swap cost?",
        "WE Air 290 price?",
        "What are WE Space recharge add-ons?",
        "How can I subscribe to Salefny Extra?",
        "Compare WE Air and WE Space.",
        "Which package is better for gaming?",
        "Compare this uploaded PDF with Telecom Egypt official terms.",
    ]
    for example in examples:
        print(example)
        print(classify_query_complexity_rule_based(example))
