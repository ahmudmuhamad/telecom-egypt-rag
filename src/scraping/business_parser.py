from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


BUSINESS_PORTAL_URL = "https://te.eg/web/te-business"

BUSINESS_URL_PLAN: tuple[dict[str, Any], ...] = (
    {
        "business_category": "business_mobile_services",
        "business_sub_parent": "Mobile Rate Plans & solutions",
        "urls": (
            "https://te.eg/web/te-business/we-business",
            "https://te.eg/web/te-business/we-buissnes-value",
            "https://te.eg/web/te-business/we-business-prepaid",
            "https://te.eg/web/te-business/we-buissnes-internet",
            "https://te.eg/web/te-business/we-data-hub",
            "https://te.eg/web/te-business/m2m-shared-data",
            "https://te.eg/web/te-business/smart-meters",
            "https://te.eg/web/te-business/we-business-sms",
            "https://te.eg/web/te-business/fleet-tracking-service",
            "https://te.eg/web/te-business/we-air-business",
        ),
    },
    {
        "business_category": "business_data_connectivity",
        "business_sub_parent": "Enterprise Infrastructure Transit & Media",
        "urls": (
            "https://te.eg/web/te-business/business-adsl",
            "https://te.eg/web/te-business/ip-transit",
            "https://te.eg/web/te-business/ip-vpn",
            "https://te.eg/web/te-business/transmission-media",
        ),
    },
    {
        "business_category": "business_voice_services",
        "business_sub_parent": "Fixed Line & Corporate Telephony routing",
        "urls": (
            "https://te.eg/web/te-business/business-landline",
            "https://te.eg/web/te-business/voice-plans",
            "https://te.eg/web/te-business/short-number",
            "https://te.eg/web/te-business/toll-free-numbers",
            "https://te.eg/web/te-business/voice-service-0900",
            "https://te.eg/web/te-business/pri-circuit",
            "https://te.eg/web/te-business/sip-trunk-service",
            "https://te.eg/web/te-business/marketing-calls",
        ),
    },
    {
        "business_category": "business_hosting_data_center",
        "business_sub_parent": "Data Infrastructure, VPS & Racks",
        "urls": (
            "https://te.eg/web/te-business/data-center-co-location",
            "https://te.eg/web/te-business/dedicated-hosting",
            "https://te.eg/web/te-business/virtual-private-servers",
            "https://te.eg/web/te-business/shared-hosting",
        ),
    },
    {
        "business_category": "business_digital_solutions",
        "business_sub_parent": "Managed ICT, Cloud Platforms & Security",
        "urls": (
            "https://te.eg/web/te-business/we-access",
            "https://te.eg/web/te-business/ddos-protection",
            "https://te.eg/web/te-business/hosted-call-center",
            "https://te.eg/web/te-business/managed-ip-telephony",
            "https://te.eg/web/te-business/video-conferencing-meet-me",
            "https://te.eg/web/te-business/smart-solutions",
            "https://te.eg/web/te-business/e-invoice",
            "https://te.eg/web/te-business/we-cloud-erp",
            "https://te.eg/web/te-business/we-fintech",
        ),
    },
    {
        "business_category": "business_wholesale",
        "business_sub_parent": "Carrier Solutions & Peering",
        "urls": ("https://te.eg/web/te-business/wholesale",),
    },
)

URL_CATEGORY_MAP = {
    url.rstrip("/").split("/")[-1]: {
        "business_category": item["business_category"],
        "business_sub_parent": item["business_sub_parent"],
    }
    for item in BUSINESS_URL_PLAN
    for url in item["urls"]
}

BUSINESS_LINK_HINTS = (
    "/web/te-business",
    "te-business",
    "business",
    "ip-transit",
    "ip-vpn",
    "voice",
    "hosting",
    "cloud",
    "wholesale",
    "ddos",
    "data-center",
    "sip",
    "pri",
    "fwa",
    "sms",
    "fleet",
    "m2m",
    "smart",
    "e-invoice",
)
DENY_URL_HINTS = (
    "login",
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
UI_NOISE_LINES = {
    "remove",
    "add to compare",
    "compare",
    "details",
    "more details",
    "subscribe now",
    "back to top",
    "business",
    "personal",
    "menu",
    "close",
    "next",
    "previous",
    "home",
    "login",
    "search",
    "english",
    "العربية",
    "حذف",
    "أضف للمقارنة",
    "اضف للمقارنة",
    "اشترك الان",
    "اشترك الآن",
    "تفاصيل اكتر",
    "تفاصيل أكثر",
    "الرجوع الى الأعلى",
    "القائمة",
    "اغلاق",
    "إغلاق",
    "التالي",
    "السابق",
    "الرئيسية",
}
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
PRICE_RE = re.compile(
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>EGP|LE|L\.E|جنيه|ج\.م|جم|PT|قرش|قروش)",
    re.IGNORECASE,
)
QUOTA_RE = re.compile(
    r"(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>GB|G\.B|MB|M\.B|SMS|units?|minutes?|sessions?|channels?|SIMs?|invoices?|rack units?|RU|bandwidth|domains?)",
    re.IGNORECASE,
)
CODE_RE = re.compile(r"(?<!\w)(?:\*\d{2,6}(?:\*\d{1,6})*#?|#\d{2,6}\*?)(?!\w)")


@dataclass(frozen=True)
class PageContext:
    source_url: str
    listing_url: str
    final_url: str
    raw_html_path: str
    business_category: str
    business_sub_parent: str
    page_kind: str
    dynamic_fetch_used: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str | None) -> str:
    value = normalize_whitespace(value).lower()
    value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", value)
    return normalize_whitespace(value)


def detect_language(text: str) -> str | None:
    arabic_chars = len(ARABIC_RE.findall(text or ""))
    latin_chars = len(re.findall(r"[A-Za-z]", text or ""))
    if arabic_chars and latin_chars:
        return "mixed"
    if arabic_chars:
        return "ar"
    if latin_chars:
        return "en"
    return None


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def sanitize_url_filename(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path}_{parts.query}".strip("/").replace("/", "_")
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return f"{raw[:120]}_{stable_hash(url, 8)}.html"


def raw_html_path(output_dir: Path, page_kind: str, url: str) -> Path:
    return output_dir / "01_raw_html" / "business" / page_kind / sanitize_url_filename(url)


def infer_business_mapping(url: str) -> dict[str, str]:
    slug = urlsplit(url).path.rstrip("/").split("/")[-1].lower()
    return URL_CATEGORY_MAP.get(
        slug,
        {
            "business_category": "business",
            "business_sub_parent": "WE Business",
        },
    )


def is_probably_business_url(url: str) -> bool:
    lowered = url.lower()
    if any(token in lowered for token in DENY_URL_HINTS):
        return False
    if not lowered.startswith(("https://te.eg/", "http://te.eg/")):
        return False
    return any(token in lowered for token in BUSINESS_LINK_HINTS)


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href", ""))
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(base_url, href).split("#", 1)[0]
        if is_probably_business_url(full_url) and full_url not in seen:
            seen.add(full_url)
            links.append(full_url)
    return links


def clean_line(line: str) -> str:
    return normalize_whitespace(line).replace("\u200f", "").replace("\u200e", "")


def is_ui_noise_line(line: str) -> bool:
    cleaned = clean_line(line).strip("-* :")
    key = normalize_key(cleaned)
    if not key:
        return True
    if key in {normalize_key(item) for item in UI_NOISE_LINES}:
        return True
    if len(key) <= 2 and not re.search(r"\d", key):
        return True
    if PRICE_RE.search(cleaned) or QUOTA_RE.search(cleaned) or CODE_RE.search(cleaned):
        return False
    return False


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
        ".cookie",
        ".modal",
        ".social",
    ):
        for node in soup.select(selector):
            node.decompose()


def visible_lines(container: Tag | BeautifulSoup, *, max_lines: int = 320) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in container.get_text("\n", strip=True).splitlines():
        line = clean_line(raw)
        key = normalize_key(line)
        if is_ui_noise_line(line) or key in seen:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def extract_title(soup: BeautifulSoup, lines: list[str], context: PageContext) -> str:
    for selector in ("h1", "meta[property='og:title']", "title", "h2"):
        node = soup.select_one(selector)
        if not node:
            continue
        value = node.get("content", "") if node.name == "meta" else node.get_text(" ", strip=True)
        value = re.sub(r"\s*-\s*Telecom Egypt\s*$", "", normalize_whitespace(value), flags=re.I)
        if value and not is_ui_noise_line(value):
            return value
    if lines:
        return lines[0]
    slug = urlsplit(context.final_url).path.rstrip("/").split("/")[-1].replace("-", " ")
    return slug.title() or "WE Business"


def extract_description(soup: BeautifulSoup, lines: list[str]) -> str:
    node = soup.select_one("meta[name='description'], meta[property='og:description']")
    if node:
        value = normalize_whitespace(node.get("content", ""))
        if value:
            return value
    for line in lines[1:]:
        if len(line) >= 40:
            return line
    return ""


def extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.select("table")):
        headers: list[str] = []
        for row_index, row in enumerate(table.select("tr")):
            cells = [clean_line(cell.get_text(" ", strip=True)) for cell in row.select("th,td")]
            cells = [cell for cell in cells if cell and not is_ui_noise_line(cell)]
            if len(cells) < 2:
                continue
            if row_index == 0 and row.select("th"):
                headers = cells
                continue
            data = dict(zip(headers, cells, strict=False)) if headers and len(headers) == len(cells) else {
                f"column_{index + 1}": value for index, value in enumerate(cells)
            }
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
        "[class*='service']",
        "[class*='Service']",
        "[class*='offer']",
        "[class*='Offer']",
    )
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in soup.select(",".join(selectors)):
        lines = visible_lines(node, max_lines=50)
        text = "\n".join(lines)
        if len(text) < 50 or len(text) > 3000:
            continue
        if not (PRICE_RE.search(text) or QUOTA_RE.search(text) or len(lines) >= 4):
            continue
        key = stable_hash(normalize_key(text), 16)
        if key in seen:
            continue
        seen.add(key)
        heading = node.select_one("h1,h2,h3,h4,.title,[class*='title'],[class*='Title']")
        title = normalize_whitespace(heading.get_text(" ", strip=True)) if heading else lines[0]
        cards.append({"title": title, "text": text})
    return cards[:60]


def extract_terms(soup: BeautifulSoup) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for heading in soup.find_all(["h2", "h3", "h4"]):
        heading_text = normalize_whitespace(heading.get_text(" ", strip=True))
        if not re.search(r"terms|conditions|rules|الشروط|الأحكام", heading_text, re.I):
            continue
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in {"h1", "h2", "h3"}:
                break
            for line in visible_lines(sibling, max_lines=50):
                key = normalize_key(line)
                if key and key not in seen:
                    seen.add(key)
                    terms.append(line)
    return terms[:40]


def extract_features(lines: list[str]) -> list[str]:
    features: list[str] = []
    for line in lines:
        if len(line) >= 15 and not PRICE_RE.search(line):
            features.append(line)
    return unique_strings(features)[:30]


def unique_strings(values: list[str | None] | tuple[str | None, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalize_whitespace(value)
        key = normalize_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def extract_codes(text: str) -> list[str]:
    return unique_strings(list(CODE_RE.findall(text or "")))


def first_price(text: str) -> tuple[str | None, float | None]:
    match = PRICE_RE.search(text or "")
    if not match:
        return None, None
    value_text = match.group("value").replace(",", "")
    try:
        value = float(value_text)
    except ValueError:
        value = None
    unit = match.group("unit").lower()
    if value is not None and unit in {"pt", "قرش", "قروش"}:
        value = round(value / 100, 3)
    return match.group(0), value


def extract_all_prices(text: str) -> list[str]:
    return unique_strings([match.group(0) for match in PRICE_RE.finditer(text or "")])


def first_quota(text: str) -> str | None:
    match = QUOTA_RE.search(text or "")
    return match.group(0) if match else None


def infer_record_type(category: str, title: str, text: str, *, table_row: bool = False) -> str:
    lowered = f"{title} {text}".lower()
    if "hosting" in category:
        return "business_hosting_plan" if table_row or PRICE_RE.search(text) else "business_service"
    if "voice" in category:
        return "business_voice_plan" if table_row or "plan" in lowered else "business_service"
    if "connectivity" in category:
        return "business_connectivity_service"
    if "mobile" in category:
        if table_row or PRICE_RE.search(text):
            return "business_plan"
        return "business_solution" if any(token in lowered for token in ("m2m", "fleet", "smart")) else "business_service"
    if "digital" in category:
        return "business_package" if table_row or PRICE_RE.search(text) else "business_solution"
    if "wholesale" in category:
        return "business_service"
    return "detail"


def build_content(
    *,
    title: str,
    category: str,
    description: str,
    price: str | None,
    quota: str | None,
    features: list[str],
    terms: list[str],
    body_lines: list[str],
    language: str | None,
) -> str:
    category_label = category.replace("business_", "").replace("_", " ").title()
    is_arabic = language == "ar"
    parts = [
        f"{'الخدمة' if is_arabic else 'Service'}: {title}",
        f"{'الفئة' if is_arabic else 'Category'}: {category_label}",
    ]
    if description:
        parts.append(f"{'الوصف' if is_arabic else 'Description'}: {description}")
    if price:
        parts.append(f"{'السعر' if is_arabic else 'Price'}: {price}")
    if quota:
        parts.append(f"{'السعة' if is_arabic else 'Quota or allowance'}: {quota}")
    if features:
        parts.append("المميزات:" if is_arabic else "Features:")
        parts.extend(f"- {item}" for item in features[:18])
    if terms:
        parts.append("الشروط والأحكام:" if is_arabic else "Terms and conditions:")
        parts.extend(f"- {item}" for item in terms[:18])
    if body_lines:
        parts.append("التفاصيل:" if is_arabic else "Details:")
        parts.extend(body_lines[:80])
    return "\n".join(part for part in parts if part).strip()


def empty_record() -> dict[str, Any]:
    return {
        "record_id": "",
        "doc_id": "",
        "category": "business",
        "business_category": None,
        "business_sub_parent": None,
        "record_type": "detail",
        "language": None,
        "customer_segment": "business",
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": None,
        "listing_url": None,
        "detail_url": None,
        "final_url": None,
        "canonical_url": None,
        "citation_url": None,
        "title": None,
        "normalized_title": None,
        "service_name": None,
        "normalized_service_name": None,
        "plan_name": None,
        "normalized_plan_name": None,
        "description": None,
        "short_summary": None,
        "content": None,
        "index_text": None,
        "structured_data": {},
        "search_aliases": [],
        "benefits": [],
        "features": [],
        "terms_and_conditions": [],
        "requirements": [],
        "steps": [],
        "pricing_tiers": [],
        "packages": [],
        "add_ons": [],
        "codes": [],
        "ussd_codes": [],
        "price": None,
        "price_egp": None,
        "monthly_fee": None,
        "monthly_fee_egp": None,
        "monthly_fee_egp_ex_tax": None,
        "annual_fee_egp": None,
        "installation_fee_egp": None,
        "implementation_fee_egp": None,
        "quota": None,
        "quota_mb": None,
        "quota_gb": None,
        "units": None,
        "minutes": None,
        "sms": None,
        "validity": None,
        "validity_days": None,
        "raw_html_path": None,
        "last_scraped": None,
        "post_processed_at": None,
        "rag_usage": "answer_source",
        "is_accepted": True,
        "quality_score": 0.0,
        "quality_flags": [],
        "rejection_reason": "",
    }


def build_record(
    *,
    context: PageContext,
    title: str,
    description: str,
    content: str,
    structured_data: dict[str, Any],
    record_type: str,
    language: str | None,
    features: list[str] | None = None,
    terms: list[str] | None = None,
) -> dict[str, Any]:
    basis_text = "\n".join([title, description, content])
    price, price_egp = first_price(basis_text)
    quota = first_quota(basis_text)
    codes = extract_codes(basis_text)
    flags = ["scrapling_static_fetch"]
    if context.dynamic_fetch_used:
        flags.append("dynamic_fetch_used")
    doc_basis = f"{context.final_url}|{context.business_category}|{title}"
    doc_id = hashlib.sha256(doc_basis.encode("utf-8")).hexdigest()
    record_basis = f"{doc_id}|{record_type}|{stable_hash(content, 16)}"
    record = empty_record()
    record.update(
        {
            "record_id": hashlib.sha256(record_basis.encode("utf-8")).hexdigest(),
            "doc_id": doc_id,
            "business_category": context.business_category,
            "business_sub_parent": context.business_sub_parent,
            "record_type": record_type,
            "language": language,
            "source_url": context.source_url,
            "listing_url": context.listing_url,
            "detail_url": context.final_url if context.page_kind == "detail_pages" else "",
            "final_url": context.final_url,
            "canonical_url": canonical_url(context.final_url),
            "citation_url": context.final_url,
            "title": title,
            "normalized_title": normalize_key(title),
            "service_name": title if record_type in {"business_service", "business_solution", "business_connectivity_service"} else None,
            "normalized_service_name": normalize_key(title),
            "plan_name": title if record_type in {"business_plan", "business_package", "business_voice_plan", "business_hosting_plan"} else None,
            "normalized_plan_name": normalize_key(title),
            "description": description,
            "short_summary": description or content[:240],
            "content": content,
            "structured_data": {**structured_data, "prices": extract_all_prices(basis_text), "quota": quota},
            "search_aliases": [title],
            "benefits": features or [],
            "features": features or [],
            "terms_and_conditions": terms or [],
            "codes": codes,
            "ussd_codes": codes,
            "price": price,
            "price_egp": price_egp,
            "monthly_fee": price if re.search(r"monthly|month|شهري|شهر", basis_text, re.I) else None,
            "monthly_fee_egp": price_egp if re.search(r"monthly|month|شهري|شهر", basis_text, re.I) else None,
            "annual_fee_egp": price_egp if re.search(r"annual|yearly|year|سنو", basis_text, re.I) else None,
            "installation_fee_egp": price_egp if re.search(r"installation|install|تركيب", basis_text, re.I) else None,
            "implementation_fee_egp": price_egp if re.search(r"implementation|setup", basis_text, re.I) else None,
            "quota": quota,
            "raw_html_path": context.raw_html_path,
            "last_scraped": utc_now_iso(),
            "quality_flags": flags,
        }
    )
    return record


def parse_business_page(html: str, context: PageContext) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    remove_noise_nodes(soup)
    body = soup.select_one("main") or soup.select_one("[role='main']") or soup.body or soup
    lines = visible_lines(body)
    if not lines:
        return []
    title = extract_title(soup, lines, context)
    description = extract_description(soup, lines)
    text = "\n".join(lines)
    language = detect_language(text)
    terms = extract_terms(soup)
    body_lines = [line for line in lines if line not in {title, description}]
    features = extract_features(body_lines)
    records: list[dict[str, Any]] = []

    price, _ = first_price(text)
    quota = first_quota(text)
    content = build_content(
        title=title,
        category=context.business_category,
        description=description,
        price=price,
        quota=quota,
        features=features,
        terms=terms,
        body_lines=body_lines,
        language=language,
    )
    records.append(
        build_record(
            context=context,
            title=title,
            description=description,
            content=content,
            structured_data={"page_kind": context.page_kind},
            record_type=infer_record_type(context.business_category, title, text),
            language=language,
            features=features,
            terms=terms,
        )
    )

    for row in extract_tables(soup):
        row_text = row["text"]
        row_title = next(iter(row["data"].values()), title)
        row_price, _ = first_price(row_text)
        row_quota = first_quota(row_text)
        row_content = build_content(
            title=row_title,
            category=context.business_category,
            description=description,
            price=row_price,
            quota=row_quota,
            features=[],
            terms=[],
            body_lines=[row_text],
            language=language,
        )
        records.append(
            build_record(
                context=context,
                title=row_title,
                description=description,
                content=row_content,
                structured_data={"table": row},
                record_type=infer_record_type(context.business_category, row_title, row_text, table_row=True),
                language=language,
            )
        )

    for card in extract_card_blocks(soup):
        card_title = card["title"] or title
        card_text = card["text"]
        card_price, _ = first_price(card_text)
        card_quota = first_quota(card_text)
        card_content = build_content(
            title=card_title,
            category=context.business_category,
            description=description,
            price=card_price,
            quota=card_quota,
            features=extract_features(card_text.splitlines()),
            terms=[],
            body_lines=card_text.splitlines(),
            language=language,
        )
        records.append(
            build_record(
                context=context,
                title=card_title,
                description=description,
                content=card_content,
                structured_data={"card_text": card_text},
                record_type=infer_record_type(context.business_category, card_title, card_text),
                language=language,
                features=extract_features(card_text.splitlines()),
            )
        )
    return records

