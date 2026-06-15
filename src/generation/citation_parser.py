from __future__ import annotations

import re
from typing import Any


CITATION_RE = re.compile(r"\[(\d+)\]")


def extract_citation_ids(answer: str) -> set[int]:
    return {int(match) for match in CITATION_RE.findall(answer or "")}


def has_valid_citations(answer: str, sources: list[dict[str, Any]]) -> bool:
    citation_ids = extract_citation_ids(answer)
    valid_ids = {int(source.get("source_id")) for source in sources if source.get("source_id")}
    return bool(citation_ids) and citation_ids.issubset(valid_ids)


def validate_answer_grounding(
    answer: str,
    sources: list[dict[str, Any]],
    require_citations: bool = True,
    query: str = "",
) -> dict[str, Any]:
    citation_ids = extract_citation_ids(answer)
    valid_ids = {int(source.get("source_id")) for source in sources if source.get("source_id")}
    invalid_ids = sorted(citation_ids - valid_ids)
    has_citations = bool(citation_ids)
    if require_citations and not has_citations:
        return {
            "valid": False,
            "has_citations": False,
            "invalid_citation_ids": [],
            "reason": "Answer does not include citation markers.",
        }
    if invalid_ids:
        return {
            "valid": False,
            "has_citations": has_citations,
            "invalid_citation_ids": invalid_ids,
            "reason": "Answer cites source IDs that are not available.",
        }
    if has_entity_mismatch(query, answer, sources, citation_ids):
        return {
            "valid": False,
            "has_citations": has_citations,
            "invalid_citation_ids": [],
            "reason": "Answer/source entity mismatch.",
        }
    return {
        "valid": True,
        "has_citations": has_citations,
        "invalid_citation_ids": [],
        "reason": "Answer citations are valid.",
    }


def extract_required_query_entities(query: str) -> list[str]:
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


def has_entity_mismatch(
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    citation_ids: set[int],
) -> bool:
    entities = extract_required_query_entities(query)
    if not entities or not sources:
        return False
    cited_sources = [
        source for source in sources if int(source.get("source_id") or 0) in citation_ids
    ] or sources
    answer_text = (answer or "").lower()
    cited_source_text = " ".join(
        " ".join(
            str(part or "")
            for part in (
                source.get("title"),
                source.get("content"),
                source.get("snippet"),
                " ".join(
                    str(alias)
                    for alias in (source.get("metadata") or {}).get("search_aliases") or []
                )
            )
        )
        for source in cited_sources
    ).lower()
    return any(
        entity.lower() not in answer_text or entity.lower() not in cited_source_text
        for entity in entities
    )


def append_sources_section(answer: str, sources: list[dict[str, Any]]) -> str:
    if re.search(r"(?im)^sources:\s*$", answer or ""):
        return answer
    lines = [(answer or "").rstrip(), "", "Sources:"]
    for source in sources:
        source_id = source.get("source_id")
        label = source.get("citation_label") or f"Telecom Egypt - {source.get('title') or 'Source'}"
        lines.append(f"[{source_id}] {label}")
        if source.get("citation_url"):
            lines.append(str(source["citation_url"]))
    return "\n".join(lines).strip()


def parse_citations(text: str) -> list[int]:
    return sorted(extract_citation_ids(text))
