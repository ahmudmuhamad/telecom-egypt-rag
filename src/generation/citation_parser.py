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
    return {
        "valid": True,
        "has_citations": has_citations,
        "invalid_citation_ids": [],
        "reason": "Answer citations are valid.",
    }


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
