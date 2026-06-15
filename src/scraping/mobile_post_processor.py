from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.scraping.mobile_parser import (
    USSD_RE,
    extract_prices,
    extract_quota,
    normalize_key,
    normalize_whitespace,
)


VALID_CATEGORIES = {
    "prepaid",
    "control_plans",
    "postpaid",
    "mobile_internet",
    "value_added_services",
}
VALID_RECORD_TYPES = {
    "plan",
    "package",
    "add_on",
    "service_code",
    "service_detail",
    "service_fee",
    "terms",
    "benefit",
    "faq_like",
    "detail",
}
NAVIGATION_HINTS = {
    "home",
    "personal",
    "business",
    "contact us",
    "login",
    "my account",
    "search",
    "back to top",
}
MOBILE_CLEANUP_VERSION = "mobile_cleanup_v1"
UI_NOISE_PHRASES = {
    "remove",
    "add to compare",
    "compare",
    "details",
    "more details",
    "subscribe now",
    "back to top",
    "return to top",
    "mobile services details page",
    "personal",
    "home",
    "menu",
    "close",
    "next",
    "previous",
    "back",
    "add",
    "add products",
    "add product",
    "add another product",
    "clear all",
    "recharge now",
    "mobile",
    "control",
    "bundle services",
    "choose your plan",
    "recommended",
    "recommanded",
    "visit",
    "sorry. there are no products to compare",
    "\u062d\u0630\u0641",
    "\u062d\u0630\u0641 \u0627\u0644\u0643\u0644",
    "\u0623\u0636\u0641 \u0644\u0644\u0645\u0642\u0627\u0631\u0646\u0629",
    "\u0627\u0636\u0641 \u0644\u0644\u0645\u0642\u0627\u0631\u0646\u0629",
    "\u0625\u0636\u0627\u0641\u0629 \u0644\u0644\u0645\u0642\u0627\u0631\u0646\u0629",
    "\u0627\u0634\u062a\u0631\u0643 \u0627\u0644\u0627\u0646",
    "\u0627\u0634\u062a\u0631\u0643 \u0627\u0644\u0622\u0646",
    "\u062a\u0641\u0627\u0635\u064a\u0644 \u0627\u0643\u062a\u0631",
    "\u062a\u0641\u0627\u0635\u064a\u0644 \u0623\u0643\u062b\u0631",
    "\u0627\u0644\u0631\u062c\u0648\u0639 \u0627\u0644\u0649 \u0627\u0644\u0623\u0639\u0644\u0649",
    "\u0627\u0644\u0631\u062c\u0648\u0639 \u0627\u0644\u064a \u0627\u0644\u0623\u0639\u0644\u064a",
    "\u0627\u0644\u0642\u0627\u0626\u0645\u0629",
    "\u0627\u063a\u0644\u0627\u0642",
    "\u0625\u063a\u0644\u0627\u0642",
    "\u0627\u0644\u062a\u0627\u0644\u064a",
    "\u0627\u0644\u0633\u0627\u0628\u0642",
    "\u0631\u062c\u0648\u0639",
    "\u0623\u0636\u0641 \u0645\u0646\u062a\u062c",
    "\u0623\u0636\u0641 \u0645\u0646\u062a\u062c \u0622\u062e\u0631",
    "\u0627\u0644\u0645\u0642\u0627\u0631\u0646\u0629",
}
NORMALIZED_UI_NOISE_PHRASES = {normalize_key(phrase) for phrase in UI_NOISE_PHRASES}
FACT_HINT_RE = re.compile(
    r"(\d|egp|l\.e|le|pt|gb|mb|kix|\*|#|code|valid|bundle|quota|minute|sms|"
    r"\u062c\u0646\u064a\u0647|\u0642\u0631\u0634|\u0645\u064a\u062c\u0627|\u062c\u064a\u062c\u0627|"
    r"\u0643\u064a\u0643\u0633|\u0643\u0648\u062f|\u062f\u0642\u064a\u0642\u0629|"
    r"\u0635\u0644\u0627\u062d\u064a\u0629|\u0628\u0627\u0642\u0629)",
    re.IGNORECASE,
)
MOBILE_CODE_RE = re.compile(r"(?<!\w)(?:[#*][0-9][0-9#*]{1,18}[#*]?)(?!\w)")
KIX_UNIT_RE = re.compile(
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d{3,6})\s*(?:Kix|\u0643\u064a\u0643\u0633)",
    re.IGNORECASE,
)
CONSUMPTION_RULE_RE = re.compile(
    r"(?:^|\s)(?:\d+\s*)?(?:Kix|\u0643\u064a\u0643\u0633)\s*=\s*.+", re.IGNORECASE
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
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


def clean_content(content: str | None) -> str:
    lines = []
    seen: set[str] = set()
    for raw in (content or "").splitlines():
        line = normalize_whitespace(raw)
        key = normalize_key(line.lstrip("-* "))
        if not line or key in seen or key in NAVIGATION_HINTS:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def is_ui_noise_line(line: str) -> bool:
    normalized = normalize_whitespace(line).strip("-* :")
    key = normalize_key(normalized)
    if not key:
        return True
    if FACT_HINT_RE.search(normalized) and key not in NORMALIZED_UI_NOISE_PHRASES:
        return False
    return key in NORMALIZED_UI_NOISE_PHRASES


def clean_ui_noise_lines(text: str, language: str | None = None) -> str:
    del language
    output: list[str] = []
    previous_key = ""
    for raw in (text or "").splitlines():
        line = normalize_whitespace(raw)
        if is_ui_noise_line(line):
            continue
        key = normalize_key(line)
        if key and key == previous_key:
            continue
        output.append(line)
        previous_key = key
    cleaned = "\n".join(output)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_mobile_codes(text: str) -> list[str]:
    candidates: list[str] = []
    for match in MOBILE_CODE_RE.findall(text or ""):
        code = match.strip(" .,:;()[]{}")
        if len(re.sub(r"\D", "", code)) < 2:
            continue
        if "*" not in code and "#" not in code:
            continue
        candidates.append(code)
    unique = unique_strings(candidates)
    preferred: list[str] = []
    for code in sorted(unique, key=len, reverse=True):
        compact = code.replace(" ", "")
        if any(compact != other.replace(" ", "") and compact in other.replace(" ", "") for other in preferred):
            continue
        preferred.append(code)
    return list(reversed(preferred))


def line_items(values: Iterable[str | None], *, limit: int = 20) -> list[str]:
    items: list[str] = []
    for value in values:
        for raw in (value or "").splitlines():
            line = normalize_whitespace(raw).lstrip("-* ")
            if re.fullmatch(r"\d{1,4}", line):
                continue
            if line and not is_ui_noise_line(line):
                items.append(line)
    return unique_strings(items)[:limit]


def clean_description(description: str | None) -> str:
    cleaned = clean_ui_noise_lines(description or "")
    lowered = cleaned.lower()
    if "comparison card details page" in lowered or "mobile services details page" in lowered:
        return ""
    return cleaned


def extract_consumption_rules(text: str) -> list[str]:
    rules = []
    for raw in (text or "").splitlines():
        line = normalize_whitespace(raw).lstrip("-* ")
        if CONSUMPTION_RULE_RE.search(line):
            rules.append(line)
    return unique_strings(rules)


def extract_kix_units(text: str, title: str | None = None) -> int | None:
    matches = []
    for match in KIX_UNIT_RE.finditer(text or ""):
        value = int(match.group("value").replace(",", ""))
        if value >= 100:
            matches.append((match.start(), value))
    if not matches:
        return None
    title_match = re.search(r"super\s*kix\s*(\d+)", title or "", re.IGNORECASE)
    if title_match:
        price = int(title_match.group(1))
        title_pos = (text or "").lower().find(f"super kix {price}".lower())
        if title_pos >= 0:
            after_title = [item for item in matches if item[0] >= title_pos]
            if after_title:
                return after_title[0][1]
    return matches[0][1]


def record_text(record: dict[str, Any]) -> str:
    structured_data = record.get("structured_data") or {}
    parts = [
        record.get("title"),
        record.get("plan_name"),
        record.get("service_name"),
        record.get("description"),
        record.get("content"),
        structured_data.get("card_text"),
    ]
    return "\n".join(str(part) for part in parts if part)


def title_from_url(record: dict[str, Any]) -> str:
    url = record.get("detail_url") or record.get("final_url") or record.get("source_url") or ""
    slug = url.rstrip("/").split("/")[-1].split("?", 1)[0]
    slug = slug.replace("-", " ").replace("_", " ").strip()
    if not slug or slug in {"w", "guest", "mobile"}:
        return normalize_whitespace(record.get("description"))[:80] or "Mobile record"
    return " ".join(part.upper() if part in {"we", "pt"} else part.title() for part in slug.split())


def category_label(category: str | None, language: str | None) -> str:
    labels = {
        "prepaid": ("Prepaid", "\u0628\u0627\u0642\u0627\u062a \u0645\u062f\u0641\u0648\u0639\u0629 \u0645\u0642\u062f\u0645\u0627"),
        "control_plans": ("Control Plans", "\u0628\u0627\u0642\u0627\u062a \u0643\u0646\u062a\u0631\u0648\u0644"),
        "postpaid": ("Postpaid / WE Gold", "\u0628\u0627\u0642\u0627\u062a \u0648\u064a \u062c\u0648\u0644\u062f"),
        "mobile_internet": ("Mobile Internet", "\u0625\u0646\u062a\u0631\u0646\u062a \u0627\u0644\u0645\u0648\u0628\u0627\u064a\u0644"),
        "value_added_services": (
            "Value Added Services",
            "\u062e\u062f\u0645\u0627\u062a \u0625\u0636\u0627\u0641\u064a\u0629",
        ),
    }
    english, arabic = labels.get(category or "", (category or "Mobile", category or "Mobile"))
    return arabic if language == "ar" else english


def display_name(record: dict[str, Any]) -> str:
    for value in (record.get("plan_name"), record.get("service_name"), record.get("title")):
        cleaned = normalize_whitespace(value)
        if cleaned and not is_ui_noise_line(cleaned):
            return cleaned
    return title_from_url(record)


def rebuild_mobile_content(record: dict[str, Any]) -> str:
    language = record.get("language")
    is_ar = language == "ar"
    name = display_name(record)
    is_service = str(record.get("record_type", "")).startswith("service")
    benefits = line_items([*(record.get("benefits") or []), *(record.get("features") or [])])
    terms = line_items(record.get("terms_and_conditions") or [])
    consumption_rules = line_items((record.get("structured_data") or {}).get("consumption_rules") or [])
    codes = unique_strings([record.get("subscription_code"), *(record.get("ussd_codes") or [])])

    parts: list[str] = []
    if is_ar:
        name_label = "\u0627\u0644\u062e\u062f\u0645\u0629" if is_service else "\u0627\u0644\u0628\u0627\u0642\u0629"
        parts.append(f"{name_label}: {name}")
        parts.append(f"\u0627\u0644\u0641\u0626\u0629: {category_label(record.get('mobile_category'), language)}")
        if record.get("monthly_fee") or record.get("price"):
            parts.append(f"\u0627\u0644\u0633\u0639\u0631: {record.get('monthly_fee') or record.get('price')}")
        if record.get("structured_data", {}).get("kix_units"):
            parts.append(
                f"\u0627\u0644\u0648\u062d\u062f\u0627\u062a: {record['structured_data']['kix_units']:,} Kix"
            )
        if record.get("quota"):
            parts.append(f"\u0627\u0644\u0633\u0639\u0629: {record['quota']}")
        if record.get("validity"):
            parts.append(f"\u0627\u0644\u0635\u0644\u0627\u062d\u064a\u0629: {record['validity']}")
        if codes:
            parts.append(f"\u0627\u0644\u0623\u0643\u0648\u0627\u062f: {', '.join(codes)}")
            if record.get("subscription_code"):
                parts.append(f"\u0643\u0648\u062f \u0627\u0644\u0627\u0634\u062a\u0631\u0627\u0643: {record['subscription_code']}")
        if record.get("description"):
            parts.append(f"\u0627\u0644\u0648\u0635\u0641: {record['description']}")
        if benefits:
            parts.append("\u0627\u0644\u0645\u0645\u064a\u0632\u0627\u062a:")
            parts.extend(f"- {item}" for item in benefits)
        if consumption_rules:
            parts.append("\u0642\u0648\u0627\u0639\u062f \u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645:")
            parts.extend(f"- {item}" for item in consumption_rules)
        if terms:
            parts.append("\u0627\u0644\u0634\u0631\u0648\u0637 \u0648\u0627\u0644\u0623\u062d\u0643\u0627\u0645:")
            parts.extend(f"- {item}" for item in terms)
    else:
        parts.append(f"{'Service' if is_service else 'Plan'}: {name}")
        parts.append(f"Category: {category_label(record.get('mobile_category'), language)}")
        if record.get("monthly_fee") or record.get("price"):
            parts.append(f"Price: {record.get('monthly_fee') or record.get('price')}")
        if record.get("structured_data", {}).get("kix_units"):
            parts.append(f"Units: {record['structured_data']['kix_units']:,} Kix")
        if record.get("quota"):
            parts.append(f"Quota: {record['quota']}")
        if record.get("validity"):
            parts.append(f"Validity: {record['validity']}")
        if codes:
            parts.append(f"Codes: {', '.join(codes)}")
            if record.get("subscription_code"):
                parts.append(f"Subscription code: {record['subscription_code']}")
        if record.get("description"):
            parts.append(f"Description: {record['description']}")
        if benefits:
            parts.append("Benefits:")
            parts.extend(f"- {item}" for item in benefits)
        if consumption_rules:
            parts.append("Usage rules:")
            parts.extend(f"- {item}" for item in consumption_rules)
        if terms:
            parts.append("Terms and conditions:")
            parts.extend(f"- {item}" for item in terms)
    return clean_ui_noise_lines("\n".join(part for part in parts if part), language)


def enrich_search_aliases(record: dict[str, Any]) -> list[str]:
    title = display_name(record)
    aliases = [title, record.get("title"), record.get("plan_name"), record.get("service_name")]
    lowered = title.lower()
    if "super kix" in lowered:
        number = re.search(r"super\s*kix\s*(\d+)", title, re.IGNORECASE)
        suffix = f" {number.group(1)}" if number else ""
        aliases.extend(
            [
                f"Super Kix{suffix}",
                "Super Kix",
                f"\u0633\u0648\u0628\u0631 \u0643\u064a\u0643\u0633{suffix}",
                "\u0633\u0648\u0628\u0631 \u0643\u064a\u0643\u0633",
                "WE Super Kix",
                f"\u0643\u0648\u062f Super Kix{suffix}",
                f"\u0628\u0627\u0642\u0629 Super Kix{suffix}",
            ]
        )
    if "nitro" in lowered:
        aliases.extend(["Nitro", "\u0646\u064a\u062a\u0631\u0648"])
        for family in ("Nitro Prime", "Nitro Extra", "Nitro MiFi"):
            if family.lower() in lowered:
                aliases.append(family)
    if "we gold" in lowered:
        number = re.search(r"we\s*gold\s*(\d+)", title, re.IGNORECASE)
        suffix = f" {number.group(1)}" if number else ""
        aliases.extend([f"WE Gold{suffix}", f"\u0648\u064a \u062c\u0648\u0644\u062f{suffix}"])
    aliases.extend(record.get("search_aliases") or [])
    return unique_strings(aliases)[:20]


def build_index_text(record: dict[str, Any]) -> str:
    structured_data = record.get("structured_data") or {}
    parts = [
        record.get("title"),
        record.get("plan_name"),
        record.get("service_name"),
        *record.get("search_aliases", []),
        category_label(record.get("mobile_category"), record.get("language")),
        record.get("content"),
        record.get("subscription_code"),
        " ".join(record.get("ussd_codes") or []),
        record.get("price"),
        record.get("monthly_fee"),
        f"{structured_data.get('kix_units')} Kix" if structured_data.get("kix_units") else None,
    ]
    return clean_ui_noise_lines("\n".join(str(part) for part in parts if part), record.get("language"))


def clean_structured_data(structured_data: dict[str, Any], language: str | None) -> dict[str, Any]:
    cleaned = deepcopy(structured_data)
    if isinstance(cleaned.get("card_text"), str):
        cleaned["card_text"] = clean_ui_noise_lines(cleaned["card_text"], language)
    return cleaned


def cleanup_quality_score(record: dict[str, Any]) -> tuple[float, list[str], str]:
    flags = list(record.get("quality_flags") or [])
    content = record.get("content") or ""
    possible_issue = ""
    if not record.get("citation_url"):
        flags.append("no_citation_url")
        possible_issue = "no citation URL"
    if len(normalize_key(content)) < 50:
        flags.append("missing_useful_content")
        possible_issue = possible_issue or "missing useful content"
    if record.get("language") != record.get("expected_language"):
        flags.append("language_mismatch")
    if any(is_ui_noise_line(line) for line in content.splitlines()):
        flags.append("possible_ui_noise_remaining")
        possible_issue = possible_issue or "possible UI noise remaining"
    if record.get("quota") and "kix" in record_text(record).lower() and record.get("quota") in {"1 MB", "1 MBs"}:
        flags.append("possible_quota_extraction_error")
    if any(re.fullmatch(r"[#*]\d{2,3}", code) for code in record.get("ussd_codes") or []):
        flags.append("possible_partial_code")

    score = 0.55
    if record.get("citation_url"):
        score += 0.1
    if display_name(record):
        score += 0.1
    if len(content) >= 160:
        score += 0.08
    if any(
        (
            record.get("price_egp") is not None,
            record.get("monthly_fee_egp") is not None,
            bool(record.get("ussd_codes")),
            bool(record.get("structured_data", {}).get("kix_units")),
            bool(record.get("quota")),
            bool(record.get("benefits")),
            bool(record.get("terms_and_conditions")),
        )
    ):
        score += 0.12
    if "possible_ui_noise_remaining" not in flags:
        score += 0.05
    if possible_issue:
        score -= 0.08
    accepted = not possible_issue or len(content) >= 100
    if not accepted:
        flags.append("rejected_low_quality")
    return round(max(0.0, min(score, 0.98)), 2), unique_strings(flags), possible_issue


def cleanup_mobile_record(record: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(record)
    original_content = record.get("content")
    original_structured_data = deepcopy(record.get("structured_data") or {})
    original_quality_flags = list(record.get("quality_flags") or [])
    original_quality_score = record.get("quality_score")
    flags = list(original_quality_flags)

    cleaned["original_content"] = original_content
    cleaned["original_structured_data"] = original_structured_data
    cleaned["original_quality_flags"] = original_quality_flags
    cleaned["original_quality_score"] = original_quality_score
    cleaned["cleaned_at"] = utc_now_iso()
    cleaned["cleanup_version"] = MOBILE_CLEANUP_VERSION

    full_text_before = record_text(cleaned)
    structured_data = clean_structured_data(original_structured_data, cleaned.get("language"))
    content_without_noise = clean_ui_noise_lines(original_content or "", cleaned.get("language"))
    if content_without_noise != (original_content or "").strip():
        flags.append("ui_noise_removed")
    cleaned["description"] = clean_description(cleaned.get("description"))
    for field in ("title", "plan_name", "service_name"):
        if cleaned.get(field) and is_ui_noise_line(str(cleaned[field])):
            cleaned[field] = title_from_url(cleaned)
            flags.append("ui_noise_title_replaced")

    all_text = "\n".join([full_text_before, content_without_noise, structured_data.get("card_text", "")])
    old_codes = unique_strings(record.get("ussd_codes") or [])
    new_codes = extract_mobile_codes(all_text)
    if new_codes:
        if new_codes != old_codes:
            flags.append("subscription_code_normalized")
        if any(old and old != new and old in new for old in old_codes for new in new_codes):
            flags.append("partial_code_replaced")
        flags.append("subscription_code_extracted")
        cleaned["ussd_codes"] = new_codes
        cleaned["subscription_code"] = new_codes[0]
        cleaned["dial_code"] = new_codes[0]

    is_kix = bool(re.search(r"\b(super\s*)?kix\b|\u0643\u064a\u0643\u0633", all_text, re.IGNORECASE))
    if is_kix and cleaned.get("mobile_category") == "control_plans":
        kix_units = extract_kix_units(all_text, cleaned.get("title"))
        if kix_units:
            structured_data["kix_units"] = kix_units
            structured_data["unit_name"] = "Kix"
            cleaned["kix_units"] = kix_units
            cleaned["unit_name"] = "Kix"
            flags.append("kix_units_extracted")
        consumption_rules = extract_consumption_rules(all_text)
        if consumption_rules:
            structured_data["consumption_rules"] = consumption_rules
            flags.append("consumption_rules_extracted")
        quota_text = str(cleaned.get("quota") or "")
        if (
            re.search(r"\b1\s*MBs?\b|1\s*\u0645\u064a\u062c\u0627", quota_text, re.IGNORECASE)
            or "nitro mbs after 25% extra" in all_text.lower()
            or consumption_rules
        ):
            if cleaned.get("quota") or cleaned.get("quota_mb") is not None or cleaned.get("quota_gb") is not None:
                flags.append("quota_from_consumption_rule_removed")
            cleaned["quota"] = None
            cleaned["quota_mb"] = None
            cleaned["quota_gb"] = None

    cleaned["benefits"] = line_items(cleaned.get("benefits") or [])
    cleaned["features"] = line_items(cleaned.get("features") or [])
    cleaned["terms_and_conditions"] = line_items(cleaned.get("terms_and_conditions") or [], limit=30)
    cleaned["structured_data"] = structured_data
    if cleaned.get("price"):
        cleaned["price"] = clean_ui_noise_lines(str(cleaned["price"]), cleaned.get("language"))
    if cleaned.get("monthly_fee"):
        cleaned["monthly_fee"] = clean_ui_noise_lines(str(cleaned["monthly_fee"]), cleaned.get("language"))
    cleaned["search_aliases"] = enrich_search_aliases(cleaned)
    flags.append("search_aliases_enriched")
    cleaned["content"] = rebuild_mobile_content(cleaned)
    flags.append("content_rebuilt_clean")
    cleaned["index_text"] = build_index_text(cleaned)
    flags.append("index_text_built")
    structured_data["ussd_codes"] = cleaned.get("ussd_codes") or []
    structured_data["subscription_code"] = cleaned.get("subscription_code")
    structured_data["dial_code"] = cleaned.get("dial_code")
    structured_data["quota"] = cleaned.get("quota")
    structured_data["quota_mb"] = cleaned.get("quota_mb")
    structured_data["quota_gb"] = cleaned.get("quota_gb")
    cleaned["structured_data"] = structured_data
    cleaned["quality_flags"] = unique_strings(flags)
    score, final_flags, possible_issue = cleanup_quality_score(cleaned)
    cleaned["quality_score"] = score
    cleaned["quality_flags"] = final_flags
    cleaned["possible_issue"] = possible_issue
    cleaned["rejection_reason"] = "" if not possible_issue or len(cleaned.get("content") or "") >= 100 else possible_issue
    cleaned["is_accepted"] = not bool(cleaned["rejection_reason"])
    stable_record_ids(cleaned)
    return cleaned


def cleanup_mobile_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cleanup_mobile_record(record) for record in records]


def cleanup_mobile_jsonl(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    records = cleanup_mobile_records(read_jsonl(input_path))
    write_jsonl(output_path, records)
    return records


def extract_validity_days(text: str) -> tuple[str | None, int | None]:
    lowered = text.lower()
    explicit = re.search(r"(\d+)\s*(day|days|يوم|أيام|ايام)", lowered)
    if explicit:
        value = int(explicit.group(1))
        return explicit.group(0), value
    if any(token in lowered for token in ("monthly", "month", "شهر", "شهري")):
        return "monthly", 30
    if any(token in lowered for token in ("weekly", "week", "أسبوع", "اسبوع")):
        return "weekly", 7
    if "24 hours" in lowered or "24 ساعة" in lowered:
        return "24 hours", 1
    return None, None


def quality_score(record: dict[str, Any]) -> tuple[float, list[str], str]:
    flags = list(record.get("quality_flags") or [])
    score = 0.0
    rejection_reason = ""
    content = record.get("content") or ""
    title = normalize_whitespace(record.get("title"))

    if record.get("mobile_category") not in VALID_CATEGORIES:
        flags.append("wrong_category")
        rejection_reason = "wrong category"
    if record.get("record_type") not in VALID_RECORD_TYPES:
        flags.append("unknown_record_type")
        record["record_type"] = "detail"
    if title:
        score += 0.18
    else:
        flags.append("missing_title")
    if record.get("citation_url"):
        score += 0.12
    else:
        flags.append("missing_citation_url")
    content_length = len(content)
    if content_length >= 120:
        score += 0.28
    elif content_length >= 50:
        score += 0.12
    else:
        flags.append("thin_content")
    if record.get("price_egp") is not None:
        score += 0.1
    if record.get("quota_mb") is not None or record.get("quota_gb") is not None:
        score += 0.1
    if record.get("ussd_codes"):
        score += 0.12
    if record.get("benefits") or record.get("features"):
        score += 0.08
    if record.get("terms_and_conditions"):
        score += 0.08
    if record.get("description"):
        score += 0.06

    has_useful_fact = any(
        (
            record.get("price_egp") is not None,
            record.get("quota_mb") is not None,
            bool(record.get("ussd_codes")),
            bool(record.get("benefits")),
            bool(record.get("terms_and_conditions")),
            bool(record.get("description")),
        )
    )
    if not title or not record.get("citation_url") or not has_useful_fact:
        rejection_reason = rejection_reason or "missing required useful fields"
    if len(normalize_key(content)) < 40:
        rejection_reason = rejection_reason or "empty or navigation-only content"
    accepted = not rejection_reason and score >= 0.45
    if not accepted:
        flags.append("rejected_low_quality")
    return round(min(score, 1.0), 2), unique_strings(flags), rejection_reason


def stable_record_ids(record: dict[str, Any]) -> None:
    title = record.get("normalized_title") or normalize_key(record.get("title"))
    basis = "|".join(
        [
            record.get("language") or "",
            record.get("mobile_category") or "",
            record.get("record_type") or "",
            record.get("citation_url") or "",
            title,
        ]
    )
    doc_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    record_basis = f"{doc_id}|{hashlib.sha256((record.get('content') or '').encode()).hexdigest()}"
    record["doc_id"] = doc_id
    record["record_id"] = hashlib.sha256(record_basis.encode("utf-8")).hexdigest()


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    record = dict(record)
    content = clean_content(record.get("content"))
    text_for_extract = "\n".join(
        [
            normalize_whitespace(record.get("title")),
            normalize_whitespace(record.get("description")),
            content,
        ]
    )
    price, price_egp = extract_prices(text_for_extract)
    quota, quota_mb, quota_gb = extract_quota(text_for_extract)
    validity, validity_days = extract_validity_days(text_for_extract)
    ussd_codes = unique_strings([*(record.get("ussd_codes") or []), *USSD_RE.findall(text_for_extract)])

    record["category"] = "mobile"
    record["mobile_category"] = normalize_key(record.get("mobile_category")).replace(" ", "_")
    record["record_type"] = normalize_key(record.get("record_type")).replace(" ", "_") or "detail"
    record["title"] = normalize_whitespace(record.get("title"))
    record["normalized_title"] = normalize_key(record.get("title"))
    if record.get("plan_name"):
        record["plan_name"] = normalize_whitespace(record.get("plan_name"))
        record["normalized_plan_name"] = normalize_key(record.get("plan_name"))
    elif record["record_type"] in {"plan", "package", "add_on"}:
        record["plan_name"] = record["title"]
        record["normalized_plan_name"] = record["normalized_title"]
    record["description"] = normalize_whitespace(record.get("description"))
    record["short_summary"] = record["description"] or content[:240]
    record["content"] = content
    record["price"] = record.get("price") or price
    record["price_egp"] = record.get("price_egp") if record.get("price_egp") is not None else price_egp
    if record["record_type"] == "plan":
        record["monthly_fee"] = record.get("monthly_fee") or record["price"]
        record["monthly_fee_egp"] = (
            record.get("monthly_fee_egp")
            if record.get("monthly_fee_egp") is not None
            else record["price_egp"]
        )
    record["quota"] = record.get("quota") or quota
    record["quota_mb"] = record.get("quota_mb") if record.get("quota_mb") is not None else quota_mb
    record["quota_gb"] = record.get("quota_gb") if record.get("quota_gb") is not None else quota_gb
    record["validity"] = record.get("validity") or validity
    record["validity_days"] = (
        record.get("validity_days") if record.get("validity_days") is not None else validity_days
    )
    record["ussd_codes"] = ussd_codes
    record["dial_code"] = record.get("dial_code") or (ussd_codes[0] if ussd_codes else None)
    if not record.get("subscription_code") and ussd_codes:
        record["subscription_code"] = ussd_codes[0]
    record["benefits"] = unique_strings(record.get("benefits") or [])
    record["features"] = unique_strings([*(record.get("features") or []), *record["benefits"]])
    record["terms_and_conditions"] = unique_strings(record.get("terms_and_conditions") or [])
    record["search_aliases"] = unique_strings(
        [
            record.get("title"),
            record.get("plan_name"),
            record.get("service_name"),
            *(record.get("search_aliases") or []),
        ]
    )
    structured_data = dict(record.get("structured_data") or {})
    structured_data.update(
        {
            "record_type": record["record_type"],
            "price": record["price"],
            "price_egp": record["price_egp"],
            "quota": record["quota"],
            "quota_mb": record["quota_mb"],
            "quota_gb": record["quota_gb"],
            "validity": record["validity"],
            "validity_days": record["validity_days"],
            "ussd_codes": record["ussd_codes"],
        }
    )
    record["structured_data"] = structured_data
    record["rag_usage"] = "answer_source"
    record["post_processed_at"] = utc_now_iso()
    stable_record_ids(record)
    score, flags, reason = quality_score(record)
    record["quality_score"] = score
    record["quality_flags"] = flags
    record["rejection_reason"] = reason
    record["is_accepted"] = not reason and score >= 0.45
    return record


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = "|".join(
            [
                record.get("language") or "",
                record.get("mobile_category") or "",
                record.get("record_type") or "",
                record.get("citation_url") or "",
                normalize_key(record.get("title")),
                hashlib.sha256((record.get("content") or "")[:1200].encode()).hexdigest()[:12],
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def post_process_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_record(record) for record in records]
    return dedupe_records(normalized)


def post_process_jsonl(input_path: Path, output_path: Path) -> list[dict[str, Any]]:
    records = post_process_records(read_jsonl(input_path))
    write_jsonl(output_path, records)
    return records
