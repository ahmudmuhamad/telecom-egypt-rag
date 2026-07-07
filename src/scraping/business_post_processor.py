from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scraping.business_parser import (
    PRICE_RE,
    QUOTA_RE,
    UI_NOISE_LINES,
    extract_all_prices,
    first_price,
    normalize_key,
    normalize_whitespace,
)


VALID_BUSINESS_CATEGORIES = {
    "business_mobile_services",
    "business_data_connectivity",
    "business_voice_services",
    "business_hosting_data_center",
    "business_digital_solutions",
    "business_wholesale",
    "business",
}
VALID_RECORD_TYPES = {
    "business_plan",
    "business_package",
    "business_add_on",
    "business_solution",
    "business_service",
    "business_hosting_plan",
    "business_voice_plan",
    "business_connectivity_service",
    "business_terms",
    "detail",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def unique_strings(values: Iterable[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_whitespace(value)
        key = normalize_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def is_noise_line(line: str) -> bool:
    cleaned = normalize_whitespace(line).strip("-* :")
    key = normalize_key(cleaned)
    if not key:
        return True
    if key in {normalize_key(item) for item in UI_NOISE_LINES}:
        return True
    if PRICE_RE.search(cleaned) or QUOTA_RE.search(cleaned) or re.search(r"\d", cleaned):
        return False
    return False


def clean_content(text: str | None) -> tuple[str, bool]:
    output: list[str] = []
    seen: set[str] = set()
    removed = False
    for raw in (text or "").splitlines():
        line = normalize_whitespace(raw)
        if is_noise_line(line):
            removed = True
            continue
        key = normalize_key(line)
        if key in seen:
            removed = True
            continue
        seen.add(key)
        output.append(line)
    cleaned = "\n".join(output).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, removed


def extract_numeric_fields(record: dict[str, Any]) -> None:
    text = "\n".join(
        str(part)
        for part in (
            record.get("title"),
            record.get("description"),
            record.get("content"),
            json.dumps(record.get("structured_data") or {}, ensure_ascii=False),
        )
        if part
    )
    price, price_egp = first_price(text)
    if not record.get("price"):
        record["price"] = price
    if record.get("price_egp") is None:
        record["price_egp"] = price_egp
    lowered = text.lower()
    if record.get("monthly_fee_egp") is None and re.search(r"monthly|month|شهري|شهر", lowered):
        record["monthly_fee"] = record.get("monthly_fee") or record.get("price")
        record["monthly_fee_egp"] = record.get("price_egp")
    if record.get("annual_fee_egp") is None and re.search(r"annual|yearly|year|سنو", lowered):
        record["annual_fee_egp"] = record.get("price_egp")
    if record.get("installation_fee_egp") is None and re.search(r"installation|install|تركيب", lowered):
        record["installation_fee_egp"] = record.get("price_egp")
    if record.get("implementation_fee_egp") is None and re.search(r"implementation|setup", lowered):
        record["implementation_fee_egp"] = record.get("price_egp")
    quota_match = QUOTA_RE.search(text)
    if quota_match and not record.get("quota"):
        record["quota"] = quota_match.group(0)
    for field, pattern in (
        ("units", r"(\d[\d,]*)\s*units?"),
        ("minutes", r"(\d[\d,]*)\s*minutes?"),
        ("sms", r"(\d[\d,]*)\s*SMS"),
    ):
        if record.get(field) is None and (match := re.search(pattern, text, re.I)):
            record[field] = int(match.group(1).replace(",", ""))
    structured_data = dict(record.get("structured_data") or {})
    structured_data["prices"] = unique_strings([*structured_data.get("prices", []), *extract_all_prices(text)])
    record["structured_data"] = structured_data


def business_aliases(record: dict[str, Any]) -> list[str]:
    title = record.get("title")
    category = record.get("business_category")
    aliases = [title, record.get("service_name"), record.get("plan_name")]
    key = normalize_key(title)
    if "business value" in key:
        aliases.extend(["WE Business Value", "business value plan", "corporate value plan"])
    if "we business" in key:
        aliases.extend(["WE Business", "business mobile plan", "corporate mobile plan", "business control plan"])
    if "sms" in key:
        aliases.extend(["WE Business SMS", "business bulk SMS", "corporate SMS package"])
    if "data hub" in key:
        aliases.extend(["WE Data Hub", "shared corporate data pool", "corporate shared data SIMs"])
    if "air" in key or "fwa" in key:
        aliases.extend(["WE Air Business", "Business FWA", "Fixed Wireless Access business"])
    if "sip" in key:
        aliases.append("SIP Trunk")
    if "pri" in key:
        aliases.append("PRI Circuit")
    if "toll free" in key:
        aliases.append("Toll Free Numbers")
    if "0900" in key:
        aliases.append("0900 service")
    if "hosting" in key:
        aliases.extend(["Shared Hosting", "Linux cPanel hosting", "Windows Plesk hosting"])
    if "vps" in key or "virtual private" in key:
        aliases.extend(["VPS", "IaaS", "virtual server"])
    if "ddos" in key:
        aliases.append("DDoS Protection")
    if "invoice" in key:
        aliases.extend(["E-Invoice", "Egyptian Tax Authority e-invoice"])
    if category:
        aliases.append(category.replace("business_", "").replace("_", " "))
    return unique_strings([*aliases, *(record.get("search_aliases") or [])])[:30]


def build_index_text(record: dict[str, Any]) -> str:
    parts = [
        record.get("title"),
        record.get("service_name"),
        record.get("plan_name"),
        record.get("business_category", "").replace("business_", "").replace("_", " "),
        record.get("business_sub_parent"),
        *record.get("search_aliases", []),
        record.get("price"),
        record.get("monthly_fee"),
        record.get("quota"),
        str(record.get("units") or ""),
        str(record.get("minutes") or ""),
        str(record.get("sms") or ""),
        record.get("content"),
    ]
    return "\n".join(str(part) for part in parts if part).strip()


def stable_record_ids(record: dict[str, Any]) -> None:
    title = record.get("normalized_title") or normalize_key(record.get("title"))
    basis = "|".join(
        [
            record.get("business_category") or "",
            record.get("record_type") or "",
            record.get("citation_url") or "",
            title,
        ]
    )
    doc_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    content_hash = hashlib.sha256((record.get("content") or "").encode("utf-8")).hexdigest()
    record["doc_id"] = doc_id
    record["record_id"] = hashlib.sha256(f"{doc_id}|{content_hash}".encode("utf-8")).hexdigest()


def score_record(record: dict[str, Any], ui_noise_removed: bool) -> tuple[float, list[str], str]:
    flags = list(record.get("quality_flags") or [])
    if ui_noise_removed:
        flags.append("ui_noise_removed")
    reason = ""
    score = 0.0
    content = record.get("content") or ""
    if record.get("business_category") not in VALID_BUSINESS_CATEGORIES:
        flags.append("wrong_category")
        reason = "wrong category"
    if record.get("record_type") not in VALID_RECORD_TYPES:
        flags.append("unknown_record_type")
        record["record_type"] = "detail"
    if record.get("title"):
        score += 0.18
    else:
        flags.append("missing_title")
    if record.get("citation_url"):
        score += 0.12
    else:
        flags.append("missing_citation_url")
    if len(content) >= 160:
        score += 0.28
    elif len(content) >= 70:
        score += 0.14
    else:
        flags.append("thin_content")
    useful = any(
        (
            record.get("price") or record.get("price_egp") is not None,
            record.get("quota") or record.get("units") or record.get("minutes") or record.get("sms"),
            bool(record.get("features") or record.get("benefits")),
            bool(record.get("terms_and_conditions")),
            bool(record.get("description")),
        )
    )
    if useful:
        score += 0.24
    else:
        flags.append("missing_useful_fact")
        reason = reason or "missing useful text"
    if record.get("search_aliases"):
        score += 0.05
    if normalize_key(content) in {"", normalize_key(record.get("title"))}:
        reason = reason or "empty or navigation-only content"
    accepted = not reason and score >= 0.45
    if not accepted:
        flags.append("rejected_low_quality")
    return round(min(score, 1.0), 2), unique_strings(flags), "" if accepted else reason


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["category"] = "business"
    normalized["customer_segment"] = "business"
    normalized["business_category"] = normalize_key(normalized.get("business_category")).replace(" ", "_") or "business"
    normalized["record_type"] = normalize_key(normalized.get("record_type")).replace(" ", "_") or "detail"
    normalized["title"] = normalize_whitespace(normalized.get("title")) or "WE Business"
    normalized["normalized_title"] = normalize_key(normalized.get("title"))
    normalized["service_name"] = normalize_whitespace(normalized.get("service_name")) or normalized["title"]
    normalized["normalized_service_name"] = normalize_key(normalized.get("service_name"))
    if normalized["record_type"] in {"business_plan", "business_package", "business_voice_plan", "business_hosting_plan"}:
        normalized["plan_name"] = normalize_whitespace(normalized.get("plan_name")) or normalized["title"]
        normalized["normalized_plan_name"] = normalize_key(normalized.get("plan_name"))
    normalized["description"] = normalize_whitespace(normalized.get("description"))
    content, ui_noise_removed = clean_content(normalized.get("content"))
    normalized["content"] = content
    normalized["short_summary"] = normalized["description"] or content[:240]
    normalized["features"] = unique_strings(normalized.get("features") or [])
    normalized["benefits"] = unique_strings([*(normalized.get("benefits") or []), *normalized["features"]])
    normalized["terms_and_conditions"] = unique_strings(normalized.get("terms_and_conditions") or [])
    extract_numeric_fields(normalized)
    normalized["search_aliases"] = business_aliases(normalized)
    normalized["index_text"] = build_index_text(normalized)
    normalized["rag_usage"] = "answer_source"
    normalized["post_processed_at"] = utc_now_iso()
    stable_record_ids(normalized)
    score, flags, reason = score_record(normalized, ui_noise_removed)
    normalized["quality_score"] = score
    normalized["quality_flags"] = flags
    normalized["rejection_reason"] = reason
    normalized["is_accepted"] = not bool(reason)
    return normalized


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = "|".join(
            [
                record.get("business_category") or "",
                record.get("record_type") or "",
                record.get("citation_url") or "",
                normalize_key(record.get("title")),
                hashlib.sha256((record.get("content") or "")[:1500].encode("utf-8")).hexdigest()[:12],
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def post_process_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return dedupe_records([normalize_record(record) for record in records])


def post_process_jsonl(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    records = post_process_records(read_jsonl(input_path))
    write_jsonl(output_path, records)
    return records

