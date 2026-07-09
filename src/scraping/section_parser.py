from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag


ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-](?:19|20)?\d{2}\b|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?20)?\s?\d{2,4}[\s-]?\d{3,4}[\s-]?\d{3,4}(?!\w)")
DOWNLOAD_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")

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
    "products comparison",
    "compare products",
    "all rights reserved",
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
    "مقارنة المنتجات",
    "جميع الحقوق محفوظة",
}


@dataclass(frozen=True)
class PageContext:
    section: str
    category: str
    customer_segment: str
    source_url: str
    listing_url: str
    final_url: str
    raw_html_path: str
    page_kind: str
    from_cache: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str | None) -> str:
    value = normalize_whitespace(value).lower()
    value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", value)
    return normalize_whitespace(value)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/(en|ar)(/|$)", "/", parts.path, count=1, flags=re.IGNORECASE)
    path = re.sub(r"/{2,}", "/", path)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def detect_language(text: str, url: str = "") -> str | None:
    if "/ar/" in url or urlsplit(url).path.startswith("/Corporate-Sustainability"):
        return "ar"
    if "/en/" in url:
        return "en"
    arabic_chars = len(ARABIC_RE.findall(text or ""))
    latin_chars = len(re.findall(r"[A-Za-z]", text or ""))
    if arabic_chars and latin_chars:
        return "mixed"
    if arabic_chars:
        return "ar"
    if latin_chars:
        return "en"
    return None


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
        "[aria-hidden='true']",
    ):
        for node in soup.select(selector):
            node.decompose()


def visible_lines(container: Tag | BeautifulSoup, *, max_lines: int = 360) -> list[str]:
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
    return context.section.replace("_", " ").title()


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


def extract_download_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href"))
        if not href:
            continue
        absolute = urljoin(base_url, href).split("#", 1)[0]
        path = urlsplit(absolute).path.lower()
        text = normalize_whitespace(node.get_text(" ", strip=True)) or Path(path).name
        is_download = path.endswith(DOWNLOAD_EXTENSIONS)
        has_download_text = re.search(r"report|certificate|download|pdf|تقرير|شهادة|تحميل", text, re.I)
        if not (is_download or has_download_text):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({"text": text, "url": absolute})
    return links


def split_download_links(links: list[dict[str, str]]) -> tuple[list[dict[str, str]], ...]:
    reports: list[dict[str, str]] = []
    certificates: list[dict[str, str]] = []
    downloads: list[dict[str, str]] = []
    for link in links:
        text = f"{link.get('text', '')} {link.get('url', '')}"
        if re.search(r"certificate|iso|شهادة", text, re.I):
            certificates.append(link)
        elif re.search(r"report|تقرير", text, re.I):
            reports.append(link)
        else:
            downloads.append(link)
    return reports, downloads, certificates


def extract_tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.select("table")):
        rows = []
        for row in table.select("tr"):
            cells = [clean_line(cell.get_text(" ", strip=True)) for cell in row.select("th,td")]
            cells = [cell for cell in cells if cell and not is_ui_noise_line(cell)]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"table_index": table_index, "rows": rows})
    return tables


def extract_list_items(soup: BeautifulSoup) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for node in soup.select("li"):
        line = clean_line(node.get_text(" ", strip=True))
        key = normalize_key(line)
        if not line or is_ui_noise_line(line) or key in seen:
            continue
        seen.add(key)
        items.append(line)
    return items[:80]


def extract_people(lines: list[str], section: str) -> list[dict[str, str]]:
    if section != "about_te":
        return []
    people: list[dict[str, str]] = []
    title_hints = (
        "chairman",
        "chief",
        "officer",
        "director",
        "ceo",
        "cfo",
        "cto",
        "رئيس",
        "عضو",
        "مدير",
        "تنفيذي",
    )
    for index, line in enumerate(lines):
        if len(line) > 90 or not re.search(r"[A-Za-z\u0600-\u06ff]{3,}", line):
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if any(hint in next_line.lower() for hint in title_hints) or any(
            hint in line.lower() for hint in title_hints
        ):
            people.append({"name": line, "title": next_line})
    return dedupe_dicts(people)[:40]


def extract_cards(soup: BeautifulSoup) -> list[dict[str, str]]:
    selectors = (
        "article",
        ".card",
        "[class*='card']",
        "[class*='member']",
        "[class*='award']",
        "[class*='timeline']",
        "[class*='news']",
    )
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in soup.select(",".join(selectors)):
        lines = visible_lines(node, max_lines=45)
        text = "\n".join(lines)
        if len(text) < 40 or len(text) > 2500:
            continue
        key = stable_hash(normalize_key(text), 14)
        if key in seen:
            continue
        seen.add(key)
        title_node = node.select_one("h1,h2,h3,h4,.title,[class*='title'],[class*='Title']")
        title = normalize_whitespace(title_node.get_text(" ", strip=True)) if title_node else lines[0]
        cards.append({"title": title, "text": text})
    return cards[:80]


def extract_contact_information(text: str) -> dict[str, Any]:
    emails = sorted(set(EMAIL_RE.findall(text)))
    phones = sorted(set(match.group(0).strip() for match in PHONE_RE.finditer(text)))
    return {"emails": emails, "phones": phones} if emails or phones else {}


def infer_topic(section: str, title: str, url: str) -> str:
    text = f"{title} {url}".lower()
    if section == "corporate_sustainability":
        if "climate" in text:
            return "Climate Change"
        if "quality" in text or "iso" in text or "esms" in text:
            return "Corporate Quality"
        if "sustainability" in text:
            return "Sustainability"
        return "Corporate Sustainability"
    if "board" in text:
        return "Board of Directors"
    if "management" in text:
        return "Management Team"
    if "museum" in text:
        return "TE Museum"
    if "history" in text:
        return "History"
    if "award" in text:
        return "Awards"
    if "strategy" in text:
        return "Corporate Strategy"
    if "press" in text:
        return "Press Releases"
    if "tv" in text:
        return "TV Ads"
    if "career" in text or "training" in text:
        return "Careers and Training"
    if "contact" in text:
        return "Contact Information"
    return "About TE"


def infer_record_type(section: str, title: str, text: str, url: str) -> str:
    lowered = f"{title} {text[:1200]} {url}".lower()
    if section == "corporate_sustainability":
        if "iso" in lowered and re.search(r"certificate|certification|شهادة", lowered):
            return "iso_certificate"
        if "esms" in lowered:
            return "esms_policy"
        if re.search(r"report|تقرير", lowered):
            if "climate" in lowered:
                return "climate_report"
            return "sustainability_report"
        if "climate" in lowered:
            return "climate_change_overview"
        if "quality" in lowered:
            return "corporate_quality_overview"
        if "ftth" in lowered or "project" in lowered:
            return "project_overview"
        return "sustainability_overview"
    if "board" in lowered or "director" in lowered or "عضو" in lowered:
        return "board_member"
    if "management" in lowered or "chief" in lowered or "تنفيذي" in lowered:
        return "management_member"
    if "museum" in lowered:
        return "museum_overview"
    if "history" in lowered or DATE_RE.search(text):
        return "history_milestone"
    if "award" in lowered:
        return "award"
    if "strategy" in lowered:
        return "corporate_strategy"
    if "press" in lowered:
        return "press_release"
    if "tv" in lowered:
        return "tv_ad"
    if "career" in lowered or "training" in lowered:
        return "career_training_overview"
    if "contact" in lowered or EMAIL_RE.search(text) or PHONE_RE.search(text):
        return "contact_information"
    if "mission" in lowered or "vision" in lowered:
        return "mission_vision"
    return "about_overview"


def build_content(
    *,
    section_name: str,
    topic: str,
    title: str,
    description: str,
    lines: list[str],
    report_links: list[dict[str, str]],
    download_links: list[dict[str, str]],
    certificate_links: list[dict[str, str]],
    language: str | None,
) -> str:
    is_ar = language == "ar"
    parts = [
        f"{'القسم' if is_ar else 'Section'}: {section_name}",
        f"{'الموضوع' if is_ar else 'Topic'}: {topic}",
        f"{'العنوان' if is_ar else 'Title'}: {title}",
    ]
    if description:
        parts.append(f"{'الوصف' if is_ar else 'Description'}: {description}")
    if lines:
        parts.append("التفاصيل:" if is_ar else "Details:")
        parts.extend(lines[:140])
    for label, values in (
        ("Report links", report_links),
        ("Download links", download_links),
        ("Certificate links", certificate_links),
    ):
        if values:
            parts.append(label + ":")
            parts.extend(f"- {link['text']}: {link['url']}" for link in values[:20])
    return "\n".join(part for part in parts if part).strip()


def build_index_text(record: dict[str, Any]) -> str:
    link_text = " ".join(
        link.get("text", "") for field in ("report_links", "download_links", "certificate_links")
        for link in record.get(field) or []
    )
    parts = [
        record.get("title"),
        record.get("section_name"),
        record.get("topic"),
        record.get("record_type"),
        " ".join(record.get("search_aliases") or []),
        link_text,
        record.get("content"),
    ]
    return "\n".join(str(part) for part in parts if part).strip()


def parse_section_page(html: str, context: PageContext) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    remove_noise_nodes(soup)
    body = soup.select_one("main") or soup.select_one("[role='main']") or soup.body or soup
    lines = visible_lines(body)
    if not lines:
        return []
    title = extract_title(soup, lines, context)
    description = extract_description(soup, lines)
    content_lines = [line for line in lines if line not in {title, description}]
    language = detect_language("\n".join(lines), context.final_url)
    section_name = context.section.replace("_", " ").title()
    topic = infer_topic(context.section, title, context.final_url)
    all_download_links = extract_download_links(soup, context.final_url)
    report_links, download_links, certificate_links = split_download_links(all_download_links)
    people = extract_people(lines, context.section)
    tables = extract_tables(soup)
    list_items = extract_list_items(soup)
    cards = extract_cards(soup)
    text = "\n".join(lines)
    contact_information = extract_contact_information(text)
    content = build_content(
        section_name=section_name,
        topic=topic,
        title=title,
        description=description,
        lines=content_lines,
        report_links=report_links,
        download_links=download_links,
        certificate_links=certificate_links,
        language=language,
    )
    base = base_record(
        context=context,
        title=title,
        description=description,
        section_name=section_name,
        topic=topic,
        content=content,
        language=language,
        structured_data={"tables": tables, "lists": list_items, "cards": cards},
        report_links=report_links,
        download_links=download_links,
        certificate_links=certificate_links,
        people=people,
        dates=sorted(set(DATE_RE.findall(text))),
        contact_information=contact_information,
    )
    base["record_type"] = infer_record_type(context.section, title, text, context.final_url)
    records = [base]
    records.extend(split_special_records(base, cards))
    return records


def base_record(
    *,
    context: PageContext,
    title: str,
    description: str,
    section_name: str,
    topic: str,
    content: str,
    language: str | None,
    structured_data: dict[str, Any],
    report_links: list[dict[str, str]],
    download_links: list[dict[str, str]],
    certificate_links: list[dict[str, str]],
    people: list[dict[str, str]],
    dates: list[str],
    contact_information: dict[str, Any],
) -> dict[str, Any]:
    doc_id = stable_hash(f"{context.section}|{canonical_url(context.final_url)}", 64)
    record_basis = f"{doc_id}|{title}|{stable_hash(content, 16)}"
    record = {
        "record_id": stable_hash(record_basis, 64),
        "doc_id": doc_id,
        "category": context.category,
        "section": context.section,
        "record_type": "overview",
        "language": language,
        "customer_segment": context.customer_segment,
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": context.source_url,
        "listing_url": context.listing_url,
        "detail_url": context.final_url if context.page_kind == "detail_pages" else "",
        "final_url": context.final_url,
        "canonical_url": canonical_url(context.final_url),
        "citation_url": context.final_url,
        "title": title,
        "normalized_title": normalize_key(title),
        "section_name": section_name,
        "topic": topic,
        "description": description,
        "short_summary": description or content[:240],
        "content": content,
        "index_text": "",
        "structured_data": structured_data,
        "search_aliases": [title, section_name, topic],
        "report_links": report_links,
        "download_links": download_links,
        "certificate_links": certificate_links,
        "people": people,
        "dates": dates,
        "features": [],
        "benefits": [],
        "terms_and_conditions": [],
        "contact_information": contact_information,
        "raw_html_path": context.raw_html_path,
        "last_scraped": utc_now_iso(),
        "quality_flags": ["scrapling_static_fetch"],
    }
    if context.from_cache:
        record["quality_flags"].append("from_cache")
    record["index_text"] = build_index_text(record)
    return record


def split_special_records(base: dict[str, Any], cards: list[dict[str, str]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for person in base.get("people") or []:
        record = child_record(base, person["name"], person.get("title") or "", "person")
        record["record_type"] = (
            "board_member" if base.get("topic") == "Board of Directors" else "management_member"
        )
        record["people"] = [person]
        records.append(record)
    for card in cards:
        card_type = infer_record_type(
            str(base.get("section")),
            card.get("title", ""),
            card.get("text", ""),
            str(base.get("final_url")),
        )
        if card_type in {"history_milestone", "award", "press_release", "tv_ad"}:
            record = child_record(base, card["title"], card["text"], card_type)
            record["record_type"] = card_type
            records.append(record)
    for link in [*(base.get("report_links") or []), *(base.get("certificate_links") or [])]:
        record_type = "iso_certificate" if link in (base.get("certificate_links") or []) else "downloadable_report"
        record = child_record(base, link["text"], link["url"], record_type)
        record["record_type"] = record_type
        records.append(record)
    return dedupe_records(records)


def child_record(base: dict[str, Any], title: str, text: str, suffix: str) -> dict[str, Any]:
    record = dict(base)
    record["title"] = title or str(base.get("title"))
    record["normalized_title"] = normalize_key(record["title"])
    record["content"] = "\n".join(
        [
            f"Section: {base.get('section_name')}",
            f"Topic: {base.get('topic')}",
            f"Title: {record['title']}",
            text,
        ]
    ).strip()
    record["short_summary"] = record["content"][:240]
    record["record_id"] = stable_hash(
        f"{base.get('doc_id')}|{suffix}|{record['title']}|{stable_hash(record['content'])}",
        64,
    )
    record["search_aliases"] = [record["title"], str(base.get("topic")), str(base.get("section_name"))]
    record["index_text"] = build_index_text(record)
    return record


def dedupe_dicts(values: list[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_key("|".join(value.values()))
        if key and key not in seen:
            seen.add(key)
            output.append(value)
    return output


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = str(record.get("record_id"))
        if key and key not in seen:
            seen.add(key)
            output.append(record)
    return output
