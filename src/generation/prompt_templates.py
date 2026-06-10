from __future__ import annotations

import re
from typing import Any

from config.settings import settings


ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-z]")


def detect_response_language(query: str) -> str:
    arabic_count = len(ARABIC_RE.findall(query or ""))
    latin_count = len(LATIN_RE.findall(query or ""))
    if arabic_count and latin_count:
        return "mixed"
    if arabic_count:
        return "ar"
    return "en"


def build_system_prompt(language: str) -> str:
    language_instruction = {
        "ar": "Answer in clear Arabic. Egyptian Arabic is acceptable if the user used dialect.",
        "mixed": "Answer in the same mixed Arabic/English style as the user where helpful.",
        "en": "Answer in English.",
    }.get(language, "Answer in the same language as the user.")

    return "\n".join(
        [
            "You are an assistant answering questions about Telecom Egypt / WE.",
            "Use only the provided sources. Do not use outside knowledge.",
            "Do not invent prices, codes, package details, terms, or URLs.",
            "If the answer is not found in the provided sources, say so clearly.",
            "Every factual claim must cite a source using [1], [2], etc.",
            language_instruction,
            "Keep answers concise and useful.",
            "If multiple relevant options exist, use bullets or a small table.",
            "If sources conflict, mention the conflict and cite both.",
        ]
    )


def format_context_sources(
    sources: list[dict[str, Any]],
    max_sources: int | None = None,
    max_chars: int | None = None,
) -> str:
    max_sources = max_sources or settings.generation_max_context_sources
    max_chars = max_chars or settings.generation_max_context_chars
    blocks: list[str] = []
    remaining = max_chars
    for source in sources[:max_sources]:
        content = source.get("content") or source.get("snippet") or ""
        block = "\n".join(
            [
                f"[{source.get('source_id')}]",
                f"Title: {source.get('title') or ''}",
                f"Category: {source.get('category') or ''}",
                f"Record type: {source.get('record_type') or ''}",
                f"Citation URL: {source.get('citation_url') or ''}",
                "Content:",
                content,
            ]
        ).strip()
        if len(block) > remaining:
            block = block[: max(0, remaining - 3)].rstrip() + "..."
        if block:
            blocks.append(block)
            remaining -= len(block)
        if remaining <= 0:
            break
    return "\n\n".join(blocks)


def build_generation_prompt(query: str, sources: list[dict[str, Any]], language: str) -> str:
    context = format_context_sources(
        sources,
        max_sources=settings.generation_max_context_sources,
        max_chars=settings.generation_max_context_chars,
    )
    return "\n\n".join(
        [
            f"User question:\n{query}",
            f"Numbered official sources:\n{context}",
            "Instructions:",
            "- Answer using only the numbered sources.",
            "- Cite every factual statement with source markers like [1] or [2].",
            "- If the sources do not contain the answer, say the information was not found.",
            "- Do not mention scores, ranking, retrievers, or hidden metadata.",
            "- Do not include URLs inside the answer body unless directly useful; sources will be listed after.",
            f"- Response language: {language}.",
            "Answer:",
        ]
    )


def build_no_source_answer(query: str, language: str) -> str:
    if language in {"ar", "mixed"}:
        return "لم أجد هذه المعلومة في المصادر الرسمية المتاحة من Telecom Egypt."
    return "I could not find this information in the available official Telecom Egypt sources."


def build_clarification_response(route: dict[str, Any], language: str) -> str:
    if language in {"ar", "mixed"}:
        return "ممكن توضح سؤالك أكثر؟ مثل اسم الباقة أو الخدمة أو الكود الذي تريد معرفة تفاصيله."
    return "Could you clarify your question? For example, include the package, service, or code you want details about."


def build_rejection_response(route: dict[str, Any], language: str) -> str:
    if language in {"ar", "mixed"}:
        return "عذرًا، لا أستطيع المساعدة في هذا الطلب لأنه خارج نطاق مصادر Telecom Egypt الرسمية المتاحة."
    return "Sorry, I can only answer questions covered by the available official Telecom Egypt sources."


# Backward-compatible names for older imports.
SYSTEM_PROMPT = build_system_prompt("en")
RAG_PROMPT_TEMPLATE = "Context:\n{context}\n\nQuestion: {query}\nAnswer:"
