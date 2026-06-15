from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from src.retrieval.model_router import classify_query_complexity_rule_based


ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

AMBIGUOUS_QUERIES = {
    "\u0627\u0644\u0628\u0627\u0642\u0629",
    "\u0627\u0644\u0633\u0639\u0631",
    "\u0639\u0627\u064a\u0632 \u0623\u0639\u0631\u0641",
    "price?",
    "package?",
}

REJECTION_TERMS = {
    "vodafone",
    "orange",
    "etisalat",
    "private customer data",
    "personal bill",
    "\u0641\u0648\u062f\u0627\u0641\u0648\u0646",
    "\u0627\u0648\u0631\u0627\u0646\u062c",
    "\u0627\u062a\u0635\u0627\u0644\u0627\u062a",
}

UNSAFE_REJECTION_TERMS = {
    "illegal bypass",
    "bypass",
    "hacking",
    "hack",
}

CATEGORY_RULES: dict[str, tuple[str, ...]] = {
    "faq": (
        "sim swap",
        "customer service number",
        "useful numbers",
        "bill payment dates",
        "line validity",
        "fixed voice",
        "\u062e\u062f\u0645\u0629 \u0627\u0644\u0639\u0645\u0644\u0627\u0621",
        "\u0623\u0631\u0642\u0627\u0645 \u062a\u0647\u0645\u0643",
        "\u0645\u0648\u0627\u0639\u064a\u062f \u0633\u062f\u0627\u062f",
        "\u0627\u0644\u062e\u0637 \u0627\u0644\u0623\u0631\u0636\u064a",
    ),
    "devices": (
        "router",
        "device",
        "phone",
        "cordless",
        "handset",
        "model",
        "tp-link",
        "dex",
        "d1005",
        "vn020",
        "zxhn",
        "iphone",
        "samsung",
        "tp-link",
        "tplink",
        "zte",
        "huawei",
        "\u062c\u0647\u0627\u0632",
        "\u0631\u0627\u0648\u062a\u0631",
        "\u062a\u0644\u064a\u0641\u0648\u0646",
        "\u0645\u0648\u0628\u0627\u064a\u0644",
        "\u0647\u0627\u062a\u0641",
        "\u0644\u0627\u0633\u0644\u0643\u064a",
        "\u0645\u0648\u062f\u064a\u0644",
        "\u062f\u0647 \u0627\u064a\u0647",
        "\u062f\u0627 \u0627\u064a\u0647",
        "\u0633\u0639\u0631\u0647",
        "\u0645\u0648\u0627\u0635\u0641\u0627\u062a\u0647",
    ),
    "we_home": (
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
        "\u0627\u0644\u0625\u0646\u062a\u0631\u0646\u062a \u0627\u0644\u0623\u0631\u0636\u064a",
        "\u0627\u0644\u0646\u062a \u0627\u0644\u0623\u0631\u0636\u064a",
        "\u0628\u0627\u0642\u0629 \u0627\u0646\u062a\u0631\u0646\u062a",
        "\u0627\u0646\u062a\u0631\u0646\u062a",
        "\u0646\u062a",
    ),
    "services": (
        "\u0643\u0648\u062f",
        "code",
        "\u0631\u0635\u064a\u062f",
        "balance",
        "\u0633\u0644\u0641\u0646\u064a",
        "apple pay",
        "my we",
        "\u062a\u062d\u0648\u064a\u0644 \u0631\u0635\u064a\u062f",
        "\u062e\u062f\u0645\u0629",
    ),
}


def route_query(query: str, source_mode: str = "official") -> dict[str, Any]:
    normalized = normalize_query(query)
    source_mode = normalize_source_mode(source_mode)
    language_hint = infer_language_hint(query)
    complexity_decision = decision_to_dict(
        classify_query_complexity_rule_based(query, source_mode=source_mode)
    )

    if not normalized or is_ambiguous(normalized):
        return {
            "route": "clarification",
            "source_mode": source_mode,
            "category_filter": None,
            "language_hint": language_hint,
            "reason": "Query is too short or ambiguous for reliable retrieval.",
            "metadata_filters": {},
            "complexity_decision": complexity_decision,
        }

    rejection_terms = UNSAFE_REJECTION_TERMS if source_mode in {"uploads", "both"} else (
        REJECTION_TERMS | UNSAFE_REJECTION_TERMS
    )
    if any(term in normalized for term in rejection_terms):
        return {
            "route": "rejection",
            "source_mode": source_mode,
            "category_filter": None,
            "language_hint": language_hint,
            "reason": "Query is outside Telecom Egypt official support scope or requests unsafe/private data.",
            "metadata_filters": {},
            "complexity_decision": complexity_decision,
        }

    category_filter = infer_category(normalized) if source_mode == "official" else None
    metadata_filters = {"category": category_filter} if category_filter else {}

    return {
        "route": "retrieval",
        "source_mode": source_mode,
        "category_filter": category_filter,
        "language_hint": language_hint,
        "reason": "Query appears answerable from the selected sources.",
        "metadata_filters": metadata_filters,
        "complexity_decision": complexity_decision,
    }


def infer_category(normalized_query: str) -> str | None:
    if is_device_query(normalized_query):
        return "devices"
    matches: list[str] = []
    for category, terms in CATEGORY_RULES.items():
        if any(term in normalized_query for term in terms):
            matches.append(category)
    if len(matches) == 1:
        return matches[0]
    if "devices" in matches and any(term in normalized_query for term in ("price", "\u0633\u0639\u0631")):
        return "devices"
    return None


def is_device_query(normalized_query: str) -> bool:
    device_terms = CATEGORY_RULES["devices"]
    if any(term in normalized_query for term in device_terms):
        return True
    return bool(
        re.search(r"\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]{3,}\b", normalized_query)
    )


def infer_language_hint(query: str) -> str | None:
    has_arabic = bool(ARABIC_RE.search(query))
    has_latin = bool(re.search(r"[A-Za-z]", query))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"
    if has_latin:
        return "en"
    return None


def is_ambiguous(normalized_query: str) -> bool:
    if normalized_query in AMBIGUOUS_QUERIES:
        return True
    tokens = normalized_query.split()
    return len(tokens) <= 1 and normalized_query not in {"111", "*550#", "#550*"}


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def normalize_source_mode(source_mode: str) -> str:
    normalized = (source_mode or "official").strip().lower()
    if normalized in {"upload", "uploaded"}:
        return "uploads"
    if normalized in {"mixed", "official_and_uploaded"}:
        return "both"
    if normalized not in {"official", "uploads", "both"}:
        return "official"
    return normalized


def decision_to_dict(decision: Any) -> dict[str, Any]:
    data = asdict(decision)
    for key, value in list(data.items()):
        if hasattr(value, "value"):
            data[key] = value.value
    return data


class QueryRouter:
    def route(self, query: str, source_mode: str = "official") -> dict[str, Any]:
        return route_query(query, source_mode=source_mode)
