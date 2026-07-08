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
        "ar": "أجب بالعربية. استخدم علامات الاستشهاد بنفس الصيغة [1].",
        "mixed": "Answer in the same mixed Arabic/English style as the user where helpful. Keep citation markers exactly like [1].",
        "en": "Answer in English. Use citation markers exactly like [1].",
    }.get(language, "Answer in the same language as the user. Keep citation markers exactly like [1].")
    example = {
        "ar": "مثال: كود معرفة الرصيد هو *550#، ورسوم الخدمة 5 قروش. [1]",
        "mixed": "Example: SIM Swap costs 5 LE. [1]",
        "en": "Example: SIM Swap costs 5 LE. [1]",
    }.get(language, "Example: SIM Swap costs 5 LE. [1]")

    return "\n".join(
        [
            "You are an assistant answering questions about Telecom Egypt / WE.",
            "You must answer only from the numbered sources provided in the prompt.",
            "Do not invent prices, codes, package details, terms, or URLs.",
            "Every factual sentence must include at least one citation marker.",
            "Citation markers must use the exact format [1], [2], [3].",
            "Do not write citations as Arabic numerals, parentheses, source names, URLs, or 'source 1'.",
            "Do not omit citations. If the answer uses source [1], include [1] in the answer.",
            "If the answer cannot be found in the sources, say that clearly and cite no source.",
            "Return only the final answer, not explanations about these rules.",
            "Do not include a separate Sources section; the application appends sources separately.",
            "Do not mention internal labels such as Title, Category, Record type, metadata, score, retrieval, ranking, or chunk.",
            "Convert source content into a natural answer.",
            language_instruction,
            example,
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
    if language == "ar":
        example = "\n".join(
            [
                "مثال على صيغة الإجابة:",
                "السؤال: كود معرفة الرصيد كام؟",
                "الإجابة: كود معرفة الرصيد هو *550#، ورسوم الخدمة 5 قروش. [1]",
            ]
        )
        final_requirements = "\n".join(
            [
                "متطلبات الإجابة النهائية:",
                "1. أجب على سؤال المستخدم مباشرة.",
                "2. استخدم المصادر المرقمة فقط.",
                "3. كل جملة تحتوي على معلومة يجب أن تحتوي على استشهاد مثل [1].",
                "4. استخدم أرقام استشهاد موجودة في المصادر فقط.",
                "5. لا تضع روابط URL.",
                "6. لا تضف قسم Sources أو مصادر.",
                "7. لا تذكر الميتاداتا أو البحث أو الترتيب أو سلوك النموذج.",
                "8. أعد الإجابة النهائية فقط.",
            ]
        )
        source_leakage_instruction = (
            "لا تنسخ تسميات داخلية مثل Title أو Category أو Record type. "
            "حوّل محتوى المصادر إلى إجابة طبيعية."
        )
        response_language = "العربية"
    else:
        example = "\n".join(
            [
                "Citation format example:",
                "Question: What is the SIM swap cost?",
                "Answer: SIM Swap costs 5 LE. [1]",
            ]
        )
        final_requirements = "\n".join(
            [
                "Final answer requirements:",
                "1. Answer the user's question directly.",
                "2. Use only the numbered sources.",
                "3. Every factual sentence must contain a citation like [1].",
                "4. Use citation IDs that exist in the provided sources.",
                "5. Do not include URLs.",
                "6. Do not include a Sources section.",
                "7. Do not mention internal metadata, retrieval, ranking, or model behavior.",
                "8. Return only the final answer.",
            ]
        )
        source_leakage_instruction = (
            "Do not copy internal labels such as Title, Category, Record type, Language, Source, "
            "Content, metadata, score, retrieval, ranking, or chunk. Convert source content into a natural answer."
        )
        response_language = "English" if language == "en" else language

    return "\n\n".join(
        [
            f"User question:\n{query}",
            f"Numbered official sources:\n{context}",
            example,
            "Instructions:",
            "- Answer using only the numbered sources.",
            "- Every factual sentence must include a citation marker like [1] or [2].",
            "- Citation markers must exactly match the source IDs shown above.",
            "- Do not use Arabic citation numerals, parentheses, source names, URLs, or phrases like source 1.",
            "- If the sources do not contain the answer, say the information was not found.",
            f"- {source_leakage_instruction}",
            "- Do not include URLs; sources will be listed by the application after the answer.",
            "- Do not include a separate Sources section.",
            f"- Response language: {response_language}.",
            final_requirements,
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


SYSTEM_PROMPT = build_system_prompt("en")
RAG_PROMPT_TEMPLATE = "Context:\n{context}\n\nQuestion: {query}\nAnswer:"
