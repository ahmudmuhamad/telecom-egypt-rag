from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


LANGUAGE_RE = re.compile(r"/(en|ar)(/|$)", re.IGNORECASE)
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
USSD_RE = re.compile(r"(?<!\w)(?:\*\d{2,6}(?:\*\d{1,6})*#?|#\d{2,6}\*?)(?!\w)")
PRICE_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>EGP|LE|L\.E|جنيه|ج\.م|جم|PT|قرش|قروش)",
    re.IGNORECASE,
)
QUOTA_RE = re.compile(
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>GB|G\.B|MB|M\.B|جيجابايت|جيجا|ميجابايت|ميجا)",
    re.IGNORECASE,
)

MOBILE_URL_HINTS = (
    "/personal/mobile",
    "/web/guest/personal/mobile",
    "/web/guest/w/",
    "/w/",
    "nitro",
    "super-kix",
    "we-club",
    "we-gold",
    "mobile-call-services",
)
DENY_URL_HINTS = (
    "login",
    "myaccount",
    "account",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
    "mailto:",
    "tel:",
    "javascript:",
)
NOISE_LINES = {
    "home",
    "personal",
    "business",
    "about us",
    "contact us",
    "search",
    "login",
    "my account",
    "back to top",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "english",
    "العربية",
}


@dataclass(frozen=True)
class PageContext:
    source_url: str
    listing_url: str
    final_url: str
    raw_html_path: str
    expected_language: str
    mobile_category: str
    page_kind: str
    dynamic_fetch_used: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value: str | None) -> str:
    value = normalize_whitespace(value).lower()
    value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", value)
    return normalize_whitespace(value)


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def strip_language_from_url(url: str) -> str:
    parts = urlsplit(url)
    path = LANGUAGE_RE.sub("/", parts.path, count=1)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def alternate_language_url(url: str, expected_language: str) -> str:
    other = "ar" if expected_language == "en" else "en"
    if f"/{expected_language}/" in url:
        return url.replace(f"/{expected_language}/", f"/{other}/", 1)
    return ""


def language_pair_key(url: str) -> str:
    parts = urlsplit(url)
    path = LANGUAGE_RE.sub("/", parts.path, count=1)
    key = re.sub(r"[^a-zA-Z0-9\u0600-\u06ff]+", "-", path).strip("-").lower()
    return key or stable_hash(url)


def detect_language(text: str, expected_language: str) -> str:
    sample = text[:4000]
    arabic_chars = len(ARABIC_RE.findall(sample))
    latin_chars = len(re.findall(r"[A-Za-z]", sample))
    if expected_language == "en":
        return "ar" if arabic_chars > max(100, latin_chars) else "en"
    if expected_language == "ar":
        return "en" if latin_chars > max(200, arabic_chars * 3) else "ar"
    if arabic_chars > max(30, latin_chars):
        return "ar"
    if latin_chars > 30:
        return "en"
    return expected_language


def infer_mobile_category(url: str) -> str:
    lowered = url.lower()
    if "mobile-call-services" in lowered:
        return "value_added_services"
    if any(token in lowered for token in ("nitro", "mifi")):
        return "mobile_internet"
    if any(token in lowered for token in ("we-gold", "postpaid")):
        return "postpaid"
    if any(token in lowered for token in ("control", "super-kix", "tazbeet", "we-club")):
        return "control_plans"
    if any(token in lowered for token in ("prepaid", "12pt", "agda3")):
        return "prepaid"
    return "unknown"


def infer_record_type(
    mobile_category: str,
    title: str,
    text: str,
    *,
    is_table_row: bool = False,
    is_terms: bool = False,
) -> str:
    lowered = f"{title} {text}".lower()
    if is_terms or any(token in lowered for token in ("terms", "conditions", "rules", "الشروط")):
        return "terms"
    if mobile_category == "value_added_services":
        return "service_code" if USSD_RE.search(text) else "service_detail"
    if "benefit" in lowered or "مميزات" in lowered:
        return "benefit"
    if mobile_category == "mobile_internet":
        return "package" if is_table_row or PRICE_RE.search(text) else "detail"
    if mobile_category in {"control_plans", "postpaid"}:
        return "plan"
    if mobile_category == "prepaid":
        return "package" if is_table_row or PRICE_RE.search(text) else "plan"
    return "detail"


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = LANGUAGE_RE.sub("/", parts.path, count=1)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def sanitize_url_filename(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path}_{parts.query}"
    raw = raw.strip("/").replace("/", "_")
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return f"{raw[:110]}_{stable_hash(url, 10)}.html"


def is_probably_mobile_url(url: str) -> bool:
    lowered = url.lower()
    if any(token in lowered for token in DENY_URL_HINTS):
        return False
    if not lowered.startswith(("https://te.eg/", "http://te.eg/")):
        return False
    return any(token in lowered for token in MOBILE_URL_HINTS)


def clean_line(line: str) -> str:
    line = normalize_whitespace(line)
    line = line.replace("\u200f", "").replace("\u200e", "")
    return line


def is_noise_line(line: str) -> bool:
    lowered = line.lower().strip()
    if not lowered or lowered in NOISE_LINES:
        return True
    if len(lowered) <= 2 and not lowered.isdigit():
        return True
    if lowered.startswith(("copyright", "all rights reserved")):
        return True
    return False


def visible_lines(container: Tag | BeautifulSoup, *, max_lines: int = 260) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in container.get_text("\n", strip=True).splitlines():
        line = clean_line(raw)
        key = normalize_key(line)
        if is_noise_line(line) or key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def remove_noise_nodes(soup: BeautifulSoup) -> None:
    for selector in (
        "script",
        "style",
        "noscript",
        "svg",
        "header",
        "footer",
        "nav",
        ".navbar",
        ".breadcrumb",
        ".breadcrumbs",
        ".social",
        ".cookie",
        ".modal",
    ):
        for node in soup.select(selector):
            node.decompose()


def extract_title(soup: BeautifulSoup, lines: list[str]) -> str:
    for selector in ("h1", "meta[property='og:title']", "title", "h2"):
        node = soup.select_one(selector)
        if not node:
            continue
        if node.name == "meta":
            value = node.get("content", "")
        else:
            value = node.get_text(" ", strip=True)
        value = normalize_whitespace(value)
        value = re.sub(r"\s*-\s*Telecom Egypt\s*$", "", value, flags=re.IGNORECASE)
        if value:
            return value
    return lines[0] if lines else ""


def extract_description(soup: BeautifulSoup, lines: list[str]) -> str:
    node = soup.select_one("meta[name='description'], meta[property='og:description']")
    if node:
        description = normalize_whitespace(node.get("content", ""))
        if description:
            return description
    for line in lines[1:]:
        if len(line) >= 30:
            return line
    return ""


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href", ""))
        if not href or href.startswith("#"):
            continue
        absolute = node.get("href")
        if absolute is None:
            continue
        url = soup.new_tag("a", href=absolute).get("href", "")
        full_url = url
        if not full_url.startswith(("http://", "https://")):
            from urllib.parse import urljoin

            full_url = urljoin(base_url, full_url)
        full_url = full_url.split("#", 1)[0]
        if is_probably_mobile_url(full_url) and full_url not in seen:
            seen.add(full_url)
            links.append(full_url)
    return links


def extract_ussd_codes(text: str) -> list[str]:
    codes = []
    seen = set()
    for match in USSD_RE.findall(text):
        code = match.strip()
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def extract_prices(text: str) -> tuple[str | None, float | None]:
    match = PRICE_RE.search(text)
    if not match:
        return None, None
    value_text = match.group("value").replace(",", ".")
    unit = match.group("unit")
    try:
        value = float(value_text)
    except ValueError:
        value = None
    if value is not None and unit.lower() in {"pt", "قرش", "قروش"}:
        value = round(value / 100, 3)
    return match.group(0), value


def extract_quota(text: str) -> tuple[str | None, float | None, float | None]:
    match = QUOTA_RE.search(text)
    if not match:
        return None, None, None
    value = float(match.group("value").replace(",", "."))
    unit = match.group("unit").lower()
    if unit in {"gb", "g.b", "جيجابايت", "جيجا"}:
        return match.group(0), round(value * 1024, 3), value
    return match.group(0), value, round(value / 1024, 3)


def extract_terms(soup: BeautifulSoup) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = normalize_whitespace(heading.get_text(" ", strip=True))
        lowered = heading_text.lower()
        if not any(token in lowered for token in ("terms", "conditions", "rules", "الشروط")):
            continue
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3"}:
                break
            for line in visible_lines(sibling, max_lines=30):
                key = normalize_key(line)
                if key not in seen:
                    seen.add(key)
                    terms.append(line)
    return terms[:40]


def extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.select("table")):
        table_rows = table.select("tr")
        headers: list[str] = []
        for row_index, row in enumerate(table_rows):
            cells = [clean_line(cell.get_text(" ", strip=True)) for cell in row.select("th,td")]
            cells = [cell for cell in cells if cell]
            if len(cells) < 2:
                continue
            if row_index == 0 and row.select("th"):
                headers = cells
                continue
            if headers and len(headers) == len(cells):
                data = dict(zip(headers, cells, strict=False))
            else:
                data = {f"column_{index + 1}": value for index, value in enumerate(cells)}
            rows.append(
                {
                    "table_index": table_index,
                    "row_index": row_index,
                    "data": data,
                    "text": " | ".join(cells),
                }
            )
    return rows


def extract_card_blocks(soup: BeautifulSoup) -> list[dict[str, str]]:
    selectors = (
        "article",
        ".card",
        ".package",
        ".plan",
        "[class*='package']",
        "[class*='Package']",
        "[class*='plan']",
        "[class*='Plan']",
        "[class*='offer']",
        "[class*='Offer']",
    )
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in soup.select(",".join(selectors)):
        lines = visible_lines(node, max_lines=40)
        text = "\n".join(lines)
        if len(text) < 50 or len(text) > 2500:
            continue
        if not (PRICE_RE.search(text) or QUOTA_RE.search(text) or USSD_RE.search(text)):
            continue
        key = stable_hash(normalize_key(text), 16)
        if key in seen:
            continue
        seen.add(key)
        title = ""
        heading = node.select_one("h1,h2,h3,h4,.title,[class*='title'],[class*='Title']")
        if heading:
            title = normalize_whitespace(heading.get_text(" ", strip=True))
        if not title:
            title = lines[0] if lines else ""
        cards.append({"title": title, "text": text})
    return cards[:40]


def build_content(
    *,
    title: str,
    mobile_category: str,
    description: str,
    price: str | None,
    quota: str | None,
    ussd_codes: list[str],
    benefits: list[str],
    terms: list[str],
    body_lines: list[str],
    language: str,
) -> str:
    category_label = mobile_category.replace("_", " ").title()
    if language == "ar":
        parts = [f"الخدمة/الباقة: {title}", f"الفئة: {category_label}"]
        if description:
            parts.append(f"الوصف: {description}")
        if price:
            parts.append(f"السعر: {price}")
        if quota:
            parts.append(f"السعة: {quota}")
        if ussd_codes:
            parts.append(f"الأكواد: {', '.join(ussd_codes)}")
        if benefits:
            parts.append("المميزات:")
            parts.extend(f"- {item}" for item in benefits[:12])
        if terms:
            parts.append("الشروط والأحكام:")
            parts.extend(f"- {item}" for item in terms[:12])
    else:
        parts = [f"Plan or service: {title}", f"Category: {category_label}"]
        if description:
            parts.append(f"Description: {description}")
        if price:
            parts.append(f"Price: {price}")
        if quota:
            parts.append(f"Quota: {quota}")
        if ussd_codes:
            parts.append(f"Codes: {', '.join(ussd_codes)}")
        if benefits:
            parts.append("Benefits:")
            parts.extend(f"- {item}" for item in benefits[:12])
        if terms:
            parts.append("Terms and conditions:")
            parts.extend(f"- {item}" for item in terms[:12])
    if body_lines:
        parts.append("Details:" if language != "ar" else "التفاصيل:")
        parts.extend(body_lines[:80])
    return "\n".join(part for part in parts if part).strip()


def empty_record() -> dict[str, Any]:
    return {
        "record_id": "",
        "doc_id": "",
        "category": "mobile",
        "mobile_category": None,
        "record_type": None,
        "language": None,
        "expected_language": None,
        "customer_segment": "personal",
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": None,
        "listing_url": None,
        "detail_url": None,
        "final_url": None,
        "canonical_url": None,
        "citation_url": None,
        "alternate_language_url": None,
        "language_pair_key": None,
        "title": None,
        "normalized_title": None,
        "plan_name": None,
        "normalized_plan_name": None,
        "service_name": None,
        "description": None,
        "short_summary": None,
        "content": None,
        "structured_data": {},
        "search_aliases": [],
        "benefits": [],
        "features": [],
        "terms_and_conditions": [],
        "requirements": [],
        "steps": [],
        "ussd_codes": [],
        "dial_code": None,
        "subscription_code": None,
        "price": None,
        "price_egp": None,
        "monthly_fee": None,
        "monthly_fee_egp": None,
        "quota": None,
        "quota_mb": None,
        "quota_gb": None,
        "minutes": None,
        "sms": None,
        "validity": None,
        "validity_days": None,
        "raw_html_path": None,
        "last_scraped": None,
        "rag_usage": "answer_source",
        "is_accepted": True,
        "quality_score": 0.0,
        "quality_flags": [],
    }


def build_record(
    *,
    context: PageContext,
    title: str,
    description: str,
    content: str,
    structured_data: dict[str, Any],
    record_type: str,
    language: str,
    benefits: list[str] | None = None,
    terms: list[str] | None = None,
) -> dict[str, Any]:
    text_for_extract = "\n".join([title, description, content])
    ussd_codes = extract_ussd_codes(text_for_extract)
    price, price_egp = extract_prices(text_for_extract)
    quota, quota_mb, quota_gb = extract_quota(text_for_extract)
    flags = ["scrapling_static_fetch"]
    if context.dynamic_fetch_used:
        flags.append("dynamic_fetch_used")
    if language != context.expected_language:
        flags.append("language_mismatch")
    doc_basis = f"{context.final_url}|{title}|{context.mobile_category}|{language}"
    doc_id = hashlib.sha256(doc_basis.encode("utf-8")).hexdigest()
    record_basis = f"{doc_id}|{record_type}|{stable_hash(content, 16)}"
    record = empty_record()
    record.update(
        {
            "record_id": hashlib.sha256(record_basis.encode("utf-8")).hexdigest(),
            "doc_id": doc_id,
            "mobile_category": context.mobile_category,
            "record_type": record_type,
            "language": language,
            "expected_language": context.expected_language,
            "source_url": context.source_url,
            "listing_url": context.listing_url,
            "detail_url": context.final_url if context.page_kind == "detail_pages" else "",
            "final_url": context.final_url,
            "canonical_url": canonical_url(context.final_url),
            "citation_url": context.final_url,
            "alternate_language_url": alternate_language_url(
                context.final_url, context.expected_language
            ),
            "language_pair_key": language_pair_key(context.final_url),
            "title": title,
            "normalized_title": normalize_key(title),
            "plan_name": title if record_type in {"plan", "package", "add_on"} else None,
            "normalized_plan_name": normalize_key(title)
            if record_type in {"plan", "package", "add_on"}
            else None,
            "service_name": title if record_type.startswith("service") else None,
            "description": description,
            "short_summary": description or (content[:240] if content else ""),
            "content": content,
            "structured_data": structured_data,
            "search_aliases": [title] if title else [],
            "benefits": benefits or [],
            "features": benefits or [],
            "terms_and_conditions": terms or [],
            "ussd_codes": ussd_codes,
            "dial_code": ussd_codes[0] if ussd_codes else None,
            "subscription_code": ussd_codes[0] if ussd_codes and record_type == "service_code" else None,
            "price": price,
            "price_egp": price_egp,
            "monthly_fee": price if record_type == "plan" else None,
            "monthly_fee_egp": price_egp if record_type == "plan" else None,
            "quota": quota,
            "quota_mb": quota_mb,
            "quota_gb": quota_gb,
            "raw_html_path": context.raw_html_path,
            "last_scraped": utc_now_iso(),
            "quality_flags": flags,
        }
    )
    record["structured_data"] = {
        **structured_data,
        "record_type": record_type,
        "price": price,
        "price_egp": price_egp,
        "quota": quota,
        "quota_mb": quota_mb,
        "quota_gb": quota_gb,
        "ussd_codes": ussd_codes,
    }
    return record


def parse_mobile_page(html: str, context: PageContext) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    remove_noise_nodes(soup)
    body = soup.select_one("main") or soup.select_one("[role='main']") or soup.body or soup
    lines = visible_lines(body)
    if not lines:
        return []
    title = extract_title(soup, lines)
    description = extract_description(soup, lines)
    page_text = "\n".join(lines)
    language = detect_language(page_text, context.expected_language)
    terms = extract_terms(soup)
    useful_lines = [line for line in lines if line not in {title, description}]
    benefits = useful_lines[:10]
    records: list[dict[str, Any]] = []

    if context.mobile_category != "unknown":
        price, _ = extract_prices(page_text)
        quota, _, _ = extract_quota(page_text)
        content = build_content(
            title=title,
            mobile_category=context.mobile_category,
            description=description,
            price=price,
            quota=quota,
            ussd_codes=extract_ussd_codes(page_text),
            benefits=benefits,
            terms=terms,
            body_lines=useful_lines,
            language=language,
        )
        records.append(
            build_record(
                context=context,
                title=title,
                description=description,
                content=content,
                structured_data={"page_kind": context.page_kind},
                record_type=infer_record_type(context.mobile_category, title, page_text),
                language=language,
                benefits=benefits,
                terms=terms,
            )
        )

    for row in extract_tables(soup):
        row_text = row["text"]
        row_title = next(iter(row["data"].values()), title)
        row_price, _ = extract_prices(row_text)
        row_quota, _, _ = extract_quota(row_text)
        content = build_content(
            title=row_title,
            mobile_category=context.mobile_category,
            description=description,
            price=row_price,
            quota=row_quota,
            ussd_codes=extract_ussd_codes(row_text),
            benefits=[],
            terms=[],
            body_lines=[row_text],
            language=language,
        )
        records.append(
            build_record(
                context=context,
                title=row_title,
                description=description,
                content=content,
                structured_data={"table": row},
                record_type=infer_record_type(
                    context.mobile_category, row_title, row_text, is_table_row=True
                ),
                language=language,
            )
        )

    for card in extract_card_blocks(soup):
        card_title = card["title"] or title
        card_text = card["text"]
        card_price, _ = extract_prices(card_text)
        card_quota, _, _ = extract_quota(card_text)
        content = build_content(
            title=card_title,
            mobile_category=context.mobile_category,
            description=description,
            price=card_price,
            quota=card_quota,
            ussd_codes=extract_ussd_codes(card_text),
            benefits=[],
            terms=[],
            body_lines=card_text.splitlines(),
            language=language,
        )
        records.append(
            build_record(
                context=context,
                title=card_title,
                description=description,
                content=content,
                structured_data={"card_text": card_text},
                record_type=infer_record_type(context.mobile_category, card_title, card_text),
                language=language,
            )
        )

    return records


def raw_html_path(output_dir: Path, language: str, page_kind: str, url: str) -> Path:
    return (
        output_dir
        / "01_raw_html"
        / "mobile"
        / language
        / page_kind
        / sanitize_url_filename(url)
    )
