from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup, Tag
from tqdm.auto import tqdm


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_WORKSPACE_DIR = Path("/content/drive/MyDrive/telecom_egypt_rag_colab")
DEFAULT_REPO_DIR = Path("/content/telecom-egypt-rag")
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:4b"
DEFAULT_COLLECTION_NAME = "telecom_all_sources_v2"
DEFAULT_QDRANT_IMAGE = "qdrant/qdrant:v1.14.0"
OLLAMA_ENDPOINT = "http://localhost:11434/api/embed"
QDRANT_URL = "http://localhost:6333"


@dataclass
class SectionConfig:
    name: str
    enabled: bool
    seeds: list[str]
    allow_patterns: list[str]
    deny_patterns: list[str]
    output_folder: str | None = None
    parser: str | None = None
    customer_segment: str | None = None


@dataclass
class PipelineConfig:
    workspace_dir: Path = DEFAULT_WORKSPACE_DIR
    repo_dir: Path = PROJECT_ROOT
    sections: dict[str, SectionConfig] = field(default_factory=dict)
    max_pages_per_section: int | None = 5
    concurrency: int = 2
    delay_seconds: float = 1.0
    cache: bool = True
    resume: bool = True
    force_refetch: bool = False
    dynamic: bool = False
    overwrite_processed: bool = False
    force_reembed: bool = False
    embed_batch_size: int = 1
    upsert_batch_size: int = 32
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    collection_name: str = DEFAULT_COLLECTION_NAME
    qdrant_image: str = DEFAULT_QDRANT_IMAGE


def default_sections() -> dict[str, SectionConfig]:
    deny = [
        "login",
        "signin",
        "account",
        "javascript:",
        "mailto:",
        "tel:",
        "facebook",
        "twitter",
        "linkedin",
        "youtube",
        "instagram",
    ]
    return {
        "business": SectionConfig(
            name="business",
            enabled=True,
            seeds=[
                "https://te.eg/web/te-business",
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
                "https://te.eg/web/te-business/business-adsl",
                "https://te.eg/web/te-business/ip-transit",
                "https://te.eg/web/te-business/ip-vpn",
                "https://te.eg/web/te-business/transmission-media",
                "https://te.eg/web/te-business/business-landline",
                "https://te.eg/web/te-business/voice-plans",
                "https://te.eg/web/te-business/short-number",
                "https://te.eg/web/te-business/toll-free-numbers",
                "https://te.eg/web/te-business/voice-service-0900",
                "https://te.eg/web/te-business/pri-circuit",
                "https://te.eg/web/te-business/sip-trunk-service",
                "https://te.eg/web/te-business/marketing-calls",
                "https://te.eg/web/te-business/data-center-co-location",
                "https://te.eg/web/te-business/dedicated-hosting",
                "https://te.eg/web/te-business/virtual-private-servers",
                "https://te.eg/web/te-business/shared-hosting",
                "https://te.eg/web/te-business/we-access",
                "https://te.eg/web/te-business/ddos-protection",
                "https://te.eg/web/te-business/hosted-call-center",
                "https://te.eg/web/te-business/managed-ip-telephony",
                "https://te.eg/web/te-business/video-conferencing-meet-me",
                "https://te.eg/web/te-business/smart-solutions",
                "https://te.eg/web/te-business/e-invoice",
                "https://te.eg/web/te-business/we-cloud-erp",
                "https://te.eg/web/te-business/we-fintech",
                "https://te.eg/web/te-business/wholesale",
            ],
            allow_patterns=[
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
            ],
            deny_patterns=deny,
            output_folder="business",
            parser="business",
            customer_segment="business",
        ),
        "mobile": SectionConfig(
            name="mobile",
            enabled=False,
            seeds=[
                "https://te.eg/en/personal/mobile",
                "https://te.eg/ar/personal/mobile",
            ],
            allow_patterns=[
                "/personal/mobile",
                "/web/guest/personal/mobile",
                "/web/guest/w/",
                "nitro",
                "super-kix",
                "we-club",
                "we-gold",
                "mobile-call-services",
            ],
            deny_patterns=deny,
            output_folder="mobile",
            parser="mobile",
            customer_segment="personal",
        ),
        "landline": SectionConfig("landline", False, [], ["landline"], deny),
        "support": SectionConfig("support", False, [], ["support", "faq"], deny),
        "about": SectionConfig("about", False, [], ["about"], deny),
        "personal": SectionConfig("personal", False, [], ["personal"], deny),
        "devices": SectionConfig("devices", False, [], ["devices"], deny),
        "services": SectionConfig("services", False, [], ["services"], deny),
        "we_home": SectionConfig("we_home", False, [], ["we-home", "internet"], deny),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_key(value: str | None) -> str:
    value = normalize_whitespace(value).lower()
    value = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", value)
    return normalize_whitespace(value)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sanitize_url_filename(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path}_{parts.query}".strip("/").replace("/", "_")
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return f"{raw[:120]}_{stable_hash(url, 8)}.html"


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def ensure_workspace(config: PipelineConfig) -> None:
    for relative in (
        "raw_html",
        "extracted_records",
        "processed",
        "knowledge_base",
        "chunks",
        "bm25",
        "qdrant_storage",
        "qdrant_snapshots",
        "embedded_points",
        "quality_reports",
        "logs",
        "manifests",
    ):
        (config.workspace_dir / relative).mkdir(parents=True, exist_ok=True)


def raw_html_path(config: PipelineConfig, section: str, page_kind: str, url: str) -> Path:
    return config.workspace_dir / "raw_html" / section / page_kind / sanitize_url_filename(url)


def checkpoint_path(config: PipelineConfig, section: str) -> Path:
    return config.workspace_dir / "manifests" / f"{section}_scrape_checkpoint.json"


def load_checkpoint(config: PipelineConfig, section: str) -> dict[str, Any]:
    path = checkpoint_path(config, section)
    if not config.resume or not path.exists():
        return {"fetched": {}, "failed_urls": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"fetched": {}, "failed_urls": []}


def save_checkpoint(config: PipelineConfig, section: str, data: dict[str, Any]) -> None:
    write_json(checkpoint_path(config, section), data)


def should_keep_url(url: str, section: SectionConfig) -> bool:
    lowered = url.lower()
    if not lowered.startswith(("https://te.eg/", "http://te.eg/")):
        return False
    if any(pattern.lower() in lowered for pattern in section.deny_patterns):
        return False
    return any(pattern.lower() in lowered for pattern in section.allow_patterns)


def discover_links(html: str, base_url: str, section: SectionConfig) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href"))
        if not href or href.startswith("#"):
            continue
        url = urljoin(base_url, href).split("#", 1)[0]
        if should_keep_url(url, section) and url not in seen:
            seen.add(url)
            links.append(url)
    return links


def response_html(response: Any) -> str:
    html = getattr(response, "html_content", None)
    if html is None:
        html = getattr(response, "text", "")
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    return str(html or "")


async def static_fetch(url: str) -> Any:
    from scrapling import AsyncFetcher

    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "User-Agent": "TelecomEgyptRAGColabPipeline/1.0 (+respectful section crawl)",
    }
    try:
        return await AsyncFetcher.get(
            url,
            headers=headers,
            timeout=30,
            follow_redirects="safe",
            impersonate="chrome",
            stealthy_headers=False,
        )
    except TypeError:
        return await AsyncFetcher.get(url, headers=headers, timeout=30)


async def dynamic_fetch(url: str) -> Any:
    from scrapling import DynamicFetcher

    return await asyncio.to_thread(DynamicFetcher.fetch, url, headless=True, timeout=45)


def useful_html(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    return len(soup.get_text(" ", strip=True)) >= 200


@dataclass
class FetchResult:
    url: str
    final_url: str
    html: str
    raw_html_path: Path
    page_kind: str
    status: int | None = None
    from_cache: bool = False
    dynamic_fetch_used: bool = False


class SectionScraper:
    def __init__(self, config: PipelineConfig, section: SectionConfig) -> None:
        self.config = config
        self.section = section
        self.checkpoint = load_checkpoint(config, section.name)
        self.failed_urls: list[dict[str, str]] = list(self.checkpoint.get("failed_urls") or [])
        self.pages_seen = 0
        self.last_request_at = 0.0
        self.throttle_lock = asyncio.Lock()

    async def throttle(self) -> None:
        if self.config.delay_seconds <= 0:
            return
        async with self.throttle_lock:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.config.delay_seconds:
                await asyncio.sleep(self.config.delay_seconds - elapsed)
            self.last_request_at = time.monotonic()

    async def fetch_one(self, url: str, page_kind: str) -> FetchResult | None:
        if self.config.max_pages_per_section is not None and self.pages_seen >= self.config.max_pages_per_section:
            return None
        self.pages_seen += 1
        raw_path = raw_html_path(self.config, self.section.name, page_kind, url)
        checkpoint_entry = self.checkpoint.get("fetched", {}).get(url)
        if checkpoint_entry and self.config.resume and not self.config.force_refetch:
            cached_path = Path(checkpoint_entry.get("raw_html_path", ""))
            if cached_path.exists():
                return FetchResult(
                    url=url,
                    final_url=checkpoint_entry.get("final_url") or url,
                    html=cached_path.read_text(encoding="utf-8", errors="replace"),
                    raw_html_path=cached_path,
                    page_kind=page_kind,
                    status=checkpoint_entry.get("status"),
                    from_cache=True,
                    dynamic_fetch_used=checkpoint_entry.get("dynamic_fetch_used", False),
                )
        if self.config.cache and raw_path.exists() and not self.config.force_refetch:
            return FetchResult(url, url, raw_path.read_text(encoding="utf-8", errors="replace"), raw_path, page_kind, 200, True)
        try:
            await self.throttle()
            response = await static_fetch(url)
            html = response_html(response)
            final_url = str(getattr(response, "url", url))
            status = getattr(response, "status", None)
            dynamic_used = False
            if self.config.dynamic and not useful_html(html):
                dynamic_response = await dynamic_fetch(url)
                dynamic_html = response_html(dynamic_response)
                if useful_html(dynamic_html):
                    html = dynamic_html
                    final_url = str(getattr(dynamic_response, "url", final_url))
                    status = getattr(dynamic_response, "status", status)
                    dynamic_used = True
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html, encoding="utf-8")
            self.checkpoint.setdefault("fetched", {})[url] = {
                "final_url": final_url,
                "raw_html_path": str(raw_path),
                "status": status,
                "dynamic_fetch_used": dynamic_used,
            }
            save_checkpoint(self.config, self.section.name, self.checkpoint)
            return FetchResult(url, final_url, html, raw_path, page_kind, status, False, dynamic_used)
        except Exception as exc:
            self.failed_urls.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})
            self.checkpoint["failed_urls"] = self.failed_urls
            save_checkpoint(self.config, self.section.name, self.checkpoint)
            return None

    async def fetch_many(self, tasks: list[tuple[str, str]]) -> list[FetchResult]:
        results: list[FetchResult] = []
        semaphore = asyncio.Semaphore(max(1, self.config.concurrency))

        async def run_task(task: tuple[str, str]) -> None:
            async with semaphore:
                result = await self.fetch_one(task[0], task[1])
                if result is not None:
                    results.append(result)

        await asyncio.gather(*(run_task(task) for task in tasks))
        return results

    async def run(self) -> dict[str, Any]:
        listing_tasks = [(self.section.seeds[0], "listing_pages")] if self.section.seeds else []
        detail_seed_tasks = [(url, "detail_pages") for url in self.section.seeds[1:]]
        listing_results = await self.fetch_many(listing_tasks)
        discovered: list[str] = []
        seen = set(self.section.seeds)
        for result in listing_results:
            for link in discover_links(result.html, result.final_url, self.section):
                if link not in seen:
                    seen.add(link)
                    discovered.append(link)
        detail_tasks = [*detail_seed_tasks, *[(url, "detail_pages") for url in discovered]]
        detail_results = await self.fetch_many(detail_tasks)
        results = [*listing_results, *detail_results]
        extracted = extract_records(results, self.section)
        extracted_path = self.config.workspace_dir / "extracted_records" / self.section.name / f"{self.section.name}.jsonl"
        write_jsonl(extracted_path, extracted)
        processed = post_process_records(self.section.name, extracted)
        processed_path = self.config.workspace_dir / "processed" / self.section.name / f"{self.section.name}_post_processed.jsonl"
        write_jsonl(processed_path, processed)
        repo_processed_path = copy_processed_to_repo(self.config, self.section.name, processed_path)
        quality_paths = write_quality_reports(
            self.config,
            self.section.name,
            processed,
            fetched_urls=len(results),
            failed_urls=self.failed_urls,
            extracted_path=extracted_path,
            processed_path=processed_path,
            repo_processed_path=repo_processed_path,
            started_at=utc_now_iso(),
        )
        return {
            "section": self.section.name,
            "total_urls": len(seen),
            "fetched_urls": len(results),
            "failed_urls": self.failed_urls,
            "records_extracted": len(extracted),
            "records_processed": len(processed),
            "extracted_path": str(extracted_path),
            "processed_path": str(processed_path),
            "repo_processed_path": str(repo_processed_path),
            **quality_paths,
        }


def extract_records(results: list[FetchResult], section: SectionConfig) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for result in results:
        try:
            if section.parser == "business":
                records.extend(extract_business_records(result))
            elif section.parser == "mobile":
                records.extend(extract_mobile_records(result))
            else:
                records.extend(extract_generic_records(result, section))
        except Exception as exc:
            records.append(generic_error_record(result, section, exc))
    return records


def extract_business_records(result: FetchResult) -> list[dict[str, Any]]:
    from src.scraping.business_parser import PageContext, infer_business_mapping, parse_business_page

    mapping = infer_business_mapping(result.final_url)
    context = PageContext(
        source_url=result.url,
        listing_url=result.url if result.page_kind == "listing_pages" else "",
        final_url=result.final_url,
        raw_html_path=str(result.raw_html_path),
        business_category=mapping["business_category"],
        business_sub_parent=mapping["business_sub_parent"],
        page_kind=result.page_kind,
        dynamic_fetch_used=result.dynamic_fetch_used,
    )
    output = []
    for record in parse_business_page(result.html, context):
        record.setdefault("section", "business")
        record.setdefault("raw_text", record.get("content") or "")
        record.setdefault("tables", [])
        record.setdefault("lists", [])
        record.setdefault("cards", [])
        output.append(record)
    return output


def extract_mobile_records(result: FetchResult) -> list[dict[str, Any]]:
    from src.scraping.mobile_parser import PageContext, infer_mobile_category, parse_mobile_page

    language = "ar" if "/ar/" in result.final_url else "en"
    context = PageContext(
        source_url=result.url,
        listing_url=result.url if result.page_kind == "listing_pages" else "",
        final_url=result.final_url,
        raw_html_path=str(result.raw_html_path),
        expected_language=language,
        mobile_category=infer_mobile_category(result.final_url),
        page_kind=result.page_kind,
        dynamic_fetch_used=result.dynamic_fetch_used,
    )
    output = []
    for record in parse_mobile_page(result.html, context):
        record.setdefault("section", "mobile")
        record.setdefault("raw_text", record.get("content") or "")
        record.setdefault("tables", [])
        record.setdefault("lists", [])
        record.setdefault("cards", [])
        output.append(record)
    return output


def remove_noise_nodes(soup: BeautifulSoup) -> None:
    for selector in ("script", "style", "noscript", "svg", "header", "footer", "nav", ".modal", ".cookie"):
        for node in soup.select(selector):
            node.decompose()


def visible_lines(container: Tag | BeautifulSoup, *, max_lines: int = 300) -> list[str]:
    noise = {
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
    }
    lines: list[str] = []
    seen: set[str] = set()
    for raw in container.get_text("\n", strip=True).splitlines():
        line = normalize_whitespace(raw).replace("\u200f", "").replace("\u200e", "")
        key = normalize_key(line)
        if not key or key in seen or key in noise:
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def extract_tables_and_lists(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], list[list[str]]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(soup.select("table")):
        rows = []
        for row in table.select("tr"):
            cells = [normalize_whitespace(cell.get_text(" ", strip=True)) for cell in row.select("th,td")]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if rows:
            tables.append({"table_index": table_index, "rows": rows})
    lists = []
    for list_node in soup.select("ul,ol"):
        items = [normalize_whitespace(item.get_text(" ", strip=True)) for item in list_node.select("li")]
        items = [item for item in items if item]
        if items:
            lists.append(items)
    return tables, lists


def extract_generic_records(result: FetchResult, section: SectionConfig) -> list[dict[str, Any]]:
    soup = BeautifulSoup(result.html, "lxml")
    remove_noise_nodes(soup)
    body = soup.select_one("main") or soup.select_one("[role='main']") or soup.body or soup
    lines = visible_lines(body)
    if not lines:
        return []
    title_node = soup.select_one("h1, meta[property='og:title'], title, h2")
    title = lines[0]
    if title_node:
        title = normalize_whitespace(title_node.get("content", "") if title_node.name == "meta" else title_node.get_text(" ", strip=True)) or title
    description_node = soup.select_one("meta[name='description'], meta[property='og:description']")
    description = normalize_whitespace(description_node.get("content", "")) if description_node else ""
    raw_text = "\n".join(lines)
    language = detect_language(raw_text)
    tables, lists = extract_tables_and_lists(soup)
    record_id_basis = f"{section.name}|{result.final_url}|{stable_hash(raw_text, 16)}"
    return [
        {
            "record_id": hashlib.sha256(record_id_basis.encode("utf-8")).hexdigest(),
            "doc_id": hashlib.sha256(f"{section.name}|{result.final_url}".encode("utf-8")).hexdigest(),
            "category": section.name,
            "section": section.name,
            "record_type": "detail",
            "language": language,
            "customer_segment": section.customer_segment,
            "source_name": "Telecom Egypt",
            "source_type": "official_website",
            "source_url": result.url,
            "final_url": result.final_url,
            "canonical_url": canonical_url(result.final_url),
            "citation_url": result.final_url,
            "title": title,
            "normalized_title": normalize_key(title),
            "service_name": title,
            "normalized_service_name": normalize_key(title),
            "plan_name": None,
            "normalized_plan_name": None,
            "description": description,
            "short_summary": description or raw_text[:240],
            "raw_text": raw_text,
            "content": raw_text,
            "index_text": "\n".join([title, description, raw_text]).strip(),
            "tables": tables,
            "lists": lists,
            "cards": [],
            "structured_data": {"tables": tables, "lists": lists},
            "search_aliases": [title],
            "benefits": [],
            "features": lines[1:25],
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
            "raw_html_path": str(result.raw_html_path),
            "last_scraped": utc_now_iso(),
        }
    ]


def generic_error_record(result: FetchResult, section: SectionConfig, exc: Exception) -> dict[str, Any]:
    return {
        "record_id": hashlib.sha256(f"error|{result.final_url}|{exc}".encode("utf-8")).hexdigest(),
        "doc_id": hashlib.sha256(f"error|{result.final_url}".encode("utf-8")).hexdigest(),
        "category": section.name,
        "section": section.name,
        "record_type": "detail",
        "language": None,
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": result.url,
        "final_url": result.final_url,
        "citation_url": result.final_url,
        "title": result.final_url,
        "raw_text": "",
        "content": "",
        "index_text": "",
        "raw_html_path": str(result.raw_html_path),
        "last_scraped": utc_now_iso(),
        "post_processed_at": utc_now_iso(),
        "rag_usage": "answer_source",
        "is_accepted": False,
        "quality_score": 0.0,
        "quality_flags": ["extraction_failed"],
        "rejection_reason": f"{type(exc).__name__}: {exc}",
    }


def detect_language(text: str) -> str | None:
    arabic = len(re.findall(r"[\u0600-\u06ff]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    if arabic and latin:
        return "mixed"
    if arabic:
        return "ar"
    if latin:
        return "en"
    return None


def post_process_records(section: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if section == "business":
        from src.scraping.business_post_processor import post_process_records as process

        return process(records)
    if section == "mobile":
        from src.scraping.mobile_post_processor import cleanup_mobile_records, post_process_records as process

        return cleanup_mobile_records(process(records))
    return [generic_post_process(section, record) for record in records]


def generic_post_process(section: str, record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    content = clean_content(row.get("content") or row.get("raw_text") or "")
    row["category"] = section
    row["section"] = section
    row["content"] = content
    row["index_text"] = "\n".join(
        str(part) for part in (row.get("title"), row.get("description"), content, " ".join(row.get("search_aliases") or [])) if part
    )
    row["post_processed_at"] = utc_now_iso()
    row["rag_usage"] = "answer_source"
    row["quality_flags"] = list(row.get("quality_flags") or [])
    if content != (record.get("content") or record.get("raw_text") or "").strip():
        row["quality_flags"].append("ui_noise_removed")
    row["quality_score"] = score_generic_record(row)
    row["is_accepted"] = row["quality_score"] >= 0.45
    row["rejection_reason"] = "" if row["is_accepted"] else "missing useful text"
    return row


def clean_content(text: str) -> str:
    noise = {
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
    }
    lines: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = normalize_whitespace(raw)
        key = normalize_key(line)
        if not key or key in noise or key in seen:
            continue
        seen.add(key)
        lines.append(line)
    return "\n".join(lines).strip()


def score_generic_record(record: dict[str, Any]) -> float:
    score = 0.0
    if record.get("title"):
        score += 0.2
    if record.get("citation_url"):
        score += 0.15
    if len(record.get("content") or "") >= 120:
        score += 0.35
    if record.get("features") or record.get("description") or record.get("tables") or record.get("lists"):
        score += 0.2
    if record.get("search_aliases"):
        score += 0.1
    return round(min(score, 1.0), 2)


def copy_processed_to_repo(config: PipelineConfig, section: str, processed_path: Path) -> Path:
    target_dir = config.repo_dir / "data" / "processed" / section
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{section}_post_processed.jsonl"
    if target.exists() and not config.overwrite_processed:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = target_dir / f"{section}_post_processed_{stamp}.jsonl"
    shutil.copy2(processed_path, target)
    return target


def write_quality_reports(
    config: PipelineConfig,
    section: str,
    records: list[dict[str, Any]],
    *,
    fetched_urls: int,
    failed_urls: list[dict[str, str]],
    extracted_path: Path,
    processed_path: Path,
    repo_processed_path: Path,
    started_at: str,
) -> dict[str, str]:
    report_dir = config.workspace_dir / "quality_reports" / section
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{section}_quality_report.csv"
    summary_path = report_dir / f"{section}_summary.json"
    columns = [
        "record_id",
        "title",
        "category",
        "section",
        "record_type",
        "citation_url",
        "is_accepted",
        "quality_score",
        "quality_flags",
        "rejection_reason",
        "has_price",
        "has_quota",
        "has_units",
        "has_minutes",
        "has_sms",
        "has_features",
        "has_terms",
        "content_length",
        "source_url",
        "raw_html_path",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "record_id": record.get("record_id"),
                    "title": record.get("title"),
                    "category": record.get("category"),
                    "section": record.get("section") or section,
                    "record_type": record.get("record_type"),
                    "citation_url": record.get("citation_url"),
                    "is_accepted": record.get("is_accepted"),
                    "quality_score": record.get("quality_score"),
                    "quality_flags": "|".join(record.get("quality_flags") or []),
                    "rejection_reason": record.get("rejection_reason") or record.get("possible_issue") or "",
                    "has_price": bool(record.get("price") or record.get("price_egp")),
                    "has_quota": bool(record.get("quota") or record.get("quota_mb") or record.get("quota_gb")),
                    "has_units": bool(record.get("units") or record.get("kix_units")),
                    "has_minutes": bool(record.get("minutes")),
                    "has_sms": bool(record.get("sms")),
                    "has_features": bool(record.get("features") or record.get("benefits")),
                    "has_terms": bool(record.get("terms_and_conditions")),
                    "content_length": len(record.get("content") or ""),
                    "source_url": record.get("source_url"),
                    "raw_html_path": record.get("raw_html_path"),
                }
            )
    summary = {
        "section": section,
        "total_urls": fetched_urls + len(failed_urls),
        "fetched_urls": fetched_urls,
        "failed_urls": failed_urls,
        "total_records": len(records),
        "accepted_records": sum(1 for record in records if record.get("is_accepted")),
        "rejected_records": sum(1 for record in records if not record.get("is_accepted")),
        "counts_by_category": count_by(records, "category"),
        "counts_by_record_type": count_by(records, "record_type"),
        "top_quality_flags": top_flags(records),
        "missing_price_count": sum(1 for record in records if not (record.get("price") or record.get("price_egp"))),
        "missing_quota_count": sum(1 for record in records if not (record.get("quota") or record.get("quota_mb") or record.get("quota_gb"))),
        "missing_citation_count": sum(1 for record in records if not record.get("citation_url")),
        "average_quality_score": round(
            sum(float(record.get("quality_score") or 0.0) for record in records) / max(1, len(records)),
            3,
        ),
        "output_files": {
            "extracted": str(extracted_path),
            "processed": str(processed_path),
            "repo_processed": str(repo_processed_path),
            "quality_csv": str(csv_path),
            "summary_json": str(summary_path),
        },
        "started_at": started_at,
        "completed_at": utc_now_iso(),
    }
    write_json(summary_path, summary)
    return {"quality_csv": str(csv_path), "quality_summary": str(summary_path)}


def count_by(records: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.get(field_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def top_flags(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for flag in record.get("quality_flags") or []:
            counts[str(flag)] = counts.get(str(flag), 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[1], reverse=True)[:25])


async def scrape_sections(config: PipelineConfig) -> dict[str, Any]:
    ensure_workspace(config)
    started_at = utc_now_iso()
    results = {}
    for section in config.sections.values():
        if not section.enabled:
            continue
        print(f"Scraping section: {section.name}")
        results[section.name] = await SectionScraper(config, section).run()
    manifest = {"started_at": started_at, "completed_at": utc_now_iso(), "sections": results}
    write_json(config.workspace_dir / "manifests" / "scrape_manifest.json", manifest)
    return manifest


def command_python(config: PipelineConfig) -> list[str]:
    uv_path = shutil.which("uv")
    if uv_path:
        return [uv_path, "run", "python"]
    return [sys.executable]


def run_repo_command(config: PipelineConfig, args: list[str]) -> None:
    print("$", " ".join(args))
    subprocess.run(args, cwd=config.repo_dir, check=True)


def generate_colab_kb_sources(config: PipelineConfig) -> Path:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to generate Colab kb_sources.yaml.") from exc

    original_path = config.repo_dir / "config" / "kb_sources.yaml"
    data = yaml.safe_load(original_path.read_text(encoding="utf-8")) if original_path.exists() else {"sources": []}
    sources = data.get("sources") or []
    seen_categories = {source.get("category") for source in sources}
    for section in config.sections.values():
        path = f"data/processed/{section.name}/{section.name}_post_processed.jsonl"
        matching = [source for source in sources if source.get("category") == section.name]
        for source in matching:
            source["path"] = path
            source["enabled"] = section.enabled
            source["description"] = source.get("description") or f"{section.name} records built in Colab"
        if section.enabled and section.name not in seen_categories:
            sources.append(
                {
                    "category": section.name,
                    "path": path,
                    "enabled": True,
                    "description": f"{section.name} records built in Colab",
                }
            )
    output = config.repo_dir / "config" / "kb_sources_colab.yaml"
    output.write_text(yaml.safe_dump({"sources": sources}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    shutil.copy2(output, config.workspace_dir / "manifests" / "kb_sources_colab.yaml")
    return output


def build_unified_kb(config: PipelineConfig) -> dict[str, str]:
    ensure_workspace(config)
    sources_config = generate_colab_kb_sources(config)
    py = command_python(config)
    output = config.repo_dir / "data" / "knowledge_base" / "telecom_egypt_kb_v1.jsonl"
    manifest = config.repo_dir / "data" / "knowledge_base" / "kb_manifest_v1.json"
    report = config.repo_dir / "data" / "knowledge_base" / "kb_build_report_v1.csv"
    rejected = config.repo_dir / "data" / "knowledge_base" / "kb_rejected_records_v1.jsonl"
    run_repo_command(
        config,
        [
            *py,
            "scripts/build_unified_kb.py",
            "--sources-config",
            str(sources_config.relative_to(config.repo_dir)),
            "--output",
            str(output.relative_to(config.repo_dir)),
            "--manifest",
            str(manifest.relative_to(config.repo_dir)),
            "--report",
            str(report.relative_to(config.repo_dir)),
            "--rejected",
            str(rejected.relative_to(config.repo_dir)),
        ],
    )
    copy_matching(config.repo_dir / "data" / "knowledge_base", config.workspace_dir / "knowledge_base", ["*.jsonl", "*.json", "*.csv"])
    kb_manifest = {
        "number_of_records": count_jsonl(output),
        "enabled_categories": [section.name for section in config.sections.values() if section.enabled],
        "source_files": [str(source) for source in (config.repo_dir / "data" / "processed").glob("*/*.jsonl")],
        "build_time": utc_now_iso(),
        "kb_path": str(output),
        "manifest_path": str(manifest),
    }
    write_json(config.workspace_dir / "manifests" / "kb_build_manifest.json", kb_manifest)
    return {"kb": str(output), "manifest": str(manifest), "report": str(report), "rejected": str(rejected)}


def build_chunks(config: PipelineConfig) -> dict[str, str]:
    py = command_python(config)
    output = config.repo_dir / "data" / "knowledge_base" / "telecom_egypt_kb_v1_chunks.jsonl"
    report = config.repo_dir / "data" / "knowledge_base" / "chunking_report_v1.csv"
    run_repo_command(config, [*py, "scripts/build_chunks.py", "--output", str(output.relative_to(config.repo_dir)), "--report", str(report.relative_to(config.repo_dir))])
    copy_matching(config.repo_dir / "data" / "knowledge_base", config.workspace_dir / "chunks", ["*chunks*.jsonl", "*chunking*.csv"])
    update_build_manifest(config, {"number_of_chunks": count_jsonl(output), "chunks_path": str(output), "chunk_report_path": str(report)})
    return {"chunks": str(output), "report": str(report)}


def build_bm25(config: PipelineConfig) -> dict[str, str]:
    py = command_python(config)
    output = config.repo_dir / "data" / "indexes" / "bm25_official_kb_v1.pkl"
    manifest = config.repo_dir / "data" / "indexes" / "bm25_manifest_v1.json"
    run_repo_command(config, [*py, "scripts/build_bm25_index.py", "--output", str(output.relative_to(config.repo_dir)), "--manifest", str(manifest.relative_to(config.repo_dir))])
    copy_matching(config.repo_dir / "data" / "indexes", config.workspace_dir / "bm25", ["*bm25*.pkl", "*bm25*manifest*.json"])
    update_build_manifest(config, {"bm25_file_path": str(output), "bm25_manifest_path": str(manifest)})
    return {"bm25": str(output), "manifest": str(manifest)}


def copy_matching(source_dir: Path, target_dir: Path, patterns: list[str]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for pattern in patterns:
        for path in source_dir.glob(pattern):
            if path.is_file():
                shutil.copy2(path, target_dir / path.name)


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def update_build_manifest(config: PipelineConfig, updates: dict[str, Any]) -> None:
    path = config.workspace_dir / "manifests" / "kb_build_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.update(updates)
    data["updated_at"] = utc_now_iso()
    write_json(path, data)


def install_and_start_ollama(config: PipelineConfig) -> None:
    if shutil.which("ollama") is None:
        command = "set -o pipefail; curl -fsSL https://ollama.com/install.sh | sh"
        result = subprocess.run(
            ["bash", "-lc", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout)
            raise RuntimeError(
                "Ollama install failed. In Colab, try rerunning the cell or run "
                "`!curl -fsSL https://ollama.com/install.sh | sh` manually to see "
                "the full installer output."
            )
    log_path = config.workspace_dir / "logs" / "ollama.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=log_path.open("a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
    )
    wait_for_ollama()
    subprocess.run(["ollama", "pull", config.embedding_model], check=True)


def wait_for_ollama(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=3)
            if response.status_code == 200:
                return
        except requests.RequestException:
            time.sleep(2)
    raise RuntimeError("Ollama did not become ready on http://localhost:11434.")


def start_qdrant_docker(config: PipelineConfig) -> None:
    ensure_workspace(config)
    subprocess.run(["docker", "rm", "-f", "qdrant_colab"], check=False)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "qdrant_colab",
            "-p",
            "6333:6333",
            "-v",
            f"{config.workspace_dir / 'qdrant_storage'}:/qdrant/storage",
            "-v",
            f"{config.workspace_dir / 'qdrant_snapshots'}:/qdrant/snapshots",
            config.qdrant_image,
        ],
        check=True,
    )
    wait_for_qdrant()


def wait_for_qdrant(timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            response = requests.get(f"{QDRANT_URL}/readyz", timeout=3)
            if response.status_code < 500:
                return
        except requests.RequestException:
            time.sleep(2)
    raise RuntimeError("Qdrant did not become ready on http://localhost:6333.")


def embed_text(text: str, model: str) -> list[float]:
    response = requests.post(OLLAMA_ENDPOINT, json={"model": model, "input": text}, timeout=180)
    response.raise_for_status()
    data = response.json()
    embeddings = data.get("embeddings")
    if not embeddings:
        raise RuntimeError(f"Ollama returned no embeddings: {data}")
    return embeddings[0]


def find_chunks_path(config: PipelineConfig) -> Path:
    candidates = [
        config.repo_dir / "data" / "knowledge_base" / "telecom_egypt_kb_v1_chunks.jsonl",
        *sorted((config.workspace_dir / "chunks").glob("*chunks*.jsonl")),
        *sorted((config.workspace_dir / "knowledge_base").glob("*chunks*.jsonl")),
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError("No chunks JSONL found. Run build_chunks first.")


def ensure_qdrant_collection(config: PipelineConfig, vector_size: int) -> None:
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=QDRANT_URL)
    if not client.collection_exists(config.collection_name):
        client.create_collection(
            collection_name=config.collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )
    payload_fields = [
        "source_type",
        "category",
        "record_type",
        "language",
        "kb_version",
        "doc_id",
        "chunk_id",
        "source_name",
        "customer_segment",
        "business_category",
        "mobile_category",
    ]
    for field_name in payload_fields:
        try:
            client.create_payload_index(
                collection_name=config.collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass


def generate_embeddings_and_upsert(config: PipelineConfig) -> dict[str, Any]:
    from qdrant_client import QdrantClient, models

    ensure_workspace(config)
    chunks_path = find_chunks_path(config)
    chunks = read_jsonl(chunks_path)
    if not chunks:
        raise RuntimeError(f"No chunks found in {chunks_path}.")

    started_at = utc_now_iso()
    completed_path = config.workspace_dir / "manifests" / "embedded_completed_chunk_ids.txt"
    completed = set(completed_path.read_text(encoding="utf-8").splitlines()) if completed_path.exists() and not config.force_reembed else set()
    failure_path = config.workspace_dir / "logs" / "embedding_failures.jsonl"
    points_path = config.workspace_dir / "embedded_points" / "embedded_points_v2.jsonl.gz"
    first_vector = embed_text(chunk_text(chunks[0]), config.embedding_model)
    vector_size = len(first_vector)
    ensure_qdrant_collection(config, vector_size)
    client = QdrantClient(url=QDRANT_URL)
    upsert_batch: list[models.PointStruct] = []
    points_written = 0
    failures = 0

    with gzip.open(points_path, "at", encoding="utf-8") as points_file:
        for chunk in tqdm(chunks, desc="Embedding chunks"):
            chunk_id = str(chunk.get("chunk_id") or chunk.get("id") or stable_hash(json.dumps(chunk, sort_keys=True), 24))
            if chunk_id in completed:
                continue
            try:
                vector = first_vector if points_written == 0 and chunk is chunks[0] else embed_text(chunk_text(chunk), config.embedding_model)
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))
                payload = dict(chunk)
                payload["chunk_id"] = chunk_id
                payload.setdefault("embedding_model", config.embedding_model)
                upsert_batch.append(models.PointStruct(id=point_id, vector=vector, payload=payload))
                points_file.write(json.dumps({"id": point_id, "vector": vector, "payload": payload}, ensure_ascii=False) + "\n")
                with completed_path.open("a", encoding="utf-8") as completed_file:
                    completed_file.write(chunk_id + "\n")
                completed.add(chunk_id)
                points_written += 1
                if len(upsert_batch) >= config.upsert_batch_size:
                    client.upsert(collection_name=config.collection_name, points=upsert_batch)
                    upsert_batch.clear()
            except Exception as exc:
                failures += 1
                with failure_path.open("a", encoding="utf-8") as failure_file:
                    failure_file.write(json.dumps({"chunk_id": chunk_id, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False) + "\n")
    if upsert_batch:
        client.upsert(collection_name=config.collection_name, points=upsert_batch)

    manifest = {
        "model_name": config.embedding_model,
        "vector_size": vector_size,
        "ollama_endpoint": OLLAMA_ENDPOINT,
        "number_of_embedded_chunks": points_written,
        "failures": failures,
        "start_time": started_at,
        "end_time": utc_now_iso(),
    }
    write_json(config.workspace_dir / "manifests" / "embedding_model_manifest.json", manifest)
    embedded_manifest = {
        "collection_name": config.collection_name,
        "vector_size": vector_size,
        "distance": "cosine",
        "embedding_model": config.embedding_model,
        "number_of_points": points_written,
        "file_size": points_path.stat().st_size if points_path.exists() else 0,
        "created_at": utc_now_iso(),
        "path": str(points_path),
    }
    write_json(config.workspace_dir / "embedded_points" / "embedded_points_manifest.json", embedded_manifest)
    return manifest


def chunk_text(chunk: dict[str, Any]) -> str:
    return normalize_whitespace(chunk.get("index_text") or chunk.get("content") or chunk.get("text") or chunk.get("title") or "")


def create_qdrant_snapshot(config: PipelineConfig) -> dict[str, Any]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=QDRANT_URL)
    info = client.create_snapshot(collection_name=config.collection_name)
    snapshot_name = getattr(info, "name", None) or info.get("name")
    snapshot_path = find_snapshot_file(config, str(snapshot_name))
    collection = client.get_collection(config.collection_name)
    vector_size = vector_size_from_collection(collection)
    points_count = getattr(collection, "points_count", None)
    manifest = {
        "collection_name": config.collection_name,
        "snapshot_name": snapshot_name,
        "snapshot_path": str(snapshot_path) if snapshot_path else "",
        "vector_size": vector_size,
        "points_count": points_count,
        "created_at": utc_now_iso(),
        "qdrant_image_version": config.qdrant_image,
    }
    write_json(config.workspace_dir / "manifests" / "qdrant_snapshot_manifest.json", manifest)
    print("Snapshot created successfully:")
    print(snapshot_path or snapshot_name)
    return manifest


def vector_size_from_collection(collection: Any) -> int | None:
    try:
        vectors = collection.config.params.vectors
        return getattr(vectors, "size", None)
    except AttributeError:
        return None


def find_snapshot_file(config: PipelineConfig, snapshot_name: str) -> Path | None:
    for path in (config.workspace_dir / "qdrant_snapshots").rglob(snapshot_name):
        if path.is_file():
            return path
    for path in (config.workspace_dir / "qdrant_storage").rglob(snapshot_name):
        if path.is_file():
            return path
    return None


def write_final_report(config: PipelineConfig) -> dict[str, Any]:
    scrape_manifest = read_json_file(config.workspace_dir / "manifests" / "scrape_manifest.json")
    kb_manifest = read_json_file(config.workspace_dir / "manifests" / "kb_build_manifest.json")
    embedding_manifest = read_json_file(config.workspace_dir / "manifests" / "embedding_model_manifest.json")
    snapshot_manifest = read_json_file(config.workspace_dir / "manifests" / "qdrant_snapshot_manifest.json")
    embedded_manifest = read_json_file(config.workspace_dir / "embedded_points" / "embedded_points_manifest.json")
    sections = scrape_manifest.get("sections", {})
    report = {
        "started_at": scrape_manifest.get("started_at") or utc_now_iso(),
        "completed_at": utc_now_iso(),
        "sections_scraped": list(sections),
        "pages_fetched": sum(int(value.get("fetched_urls") or 0) for value in sections.values()),
        "failed_urls": [item for value in sections.values() for item in value.get("failed_urls", [])],
        "records_extracted": sum(int(value.get("records_extracted") or 0) for value in sections.values()),
        "records_accepted": sum(count_accepted(value.get("processed_path")) for value in sections.values()),
        "records_rejected": sum(count_rejected(value.get("processed_path")) for value in sections.values()),
        "chunks_created": kb_manifest.get("number_of_chunks"),
        "bm25_index_path": kb_manifest.get("bm25_file_path"),
        "embedding_model": embedding_manifest.get("model_name", config.embedding_model),
        "vector_size": embedding_manifest.get("vector_size") or snapshot_manifest.get("vector_size"),
        "qdrant_collection_name": config.collection_name,
        "qdrant_points_count": snapshot_manifest.get("points_count") or embedded_manifest.get("number_of_points"),
        "qdrant_snapshot_path": snapshot_manifest.get("snapshot_path"),
        "embedded_points_path": embedded_manifest.get("path"),
        "quality_report_paths": sorted(str(path) for path in (config.workspace_dir / "quality_reports").glob("*/*_quality_report.csv")),
        "warnings": [],
        "next_steps": [
            "Download or copy the Qdrant snapshot from Google Drive.",
            "Upload the snapshot to your local Docker Qdrant collection.",
            "Set QDRANT_COLLECTION_NAME=telecom_all_sources_v2 locally and restart Streamlit.",
        ],
    }
    json_path = config.workspace_dir / "manifests" / "colab_full_pipeline_report.json"
    md_path = config.workspace_dir / "manifests" / "colab_full_pipeline_report.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(f"Final JSON report: {json_path}")
    print(f"Final Markdown report: {md_path}")
    return report


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def count_accepted(path_value: str | None) -> int:
    return sum(1 for record in read_jsonl(Path(path_value)) if record.get("is_accepted")) if path_value else 0


def count_rejected(path_value: str | None) -> int:
    return sum(1 for record in read_jsonl(Path(path_value)) if not record.get("is_accepted")) if path_value else 0


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Telecom Egypt RAG Colab Full Pipeline Report",
        "",
        f"- Completed at: {report.get('completed_at')}",
        f"- Sections scraped: {', '.join(report.get('sections_scraped') or [])}",
        f"- Pages fetched: {report.get('pages_fetched')}",
        f"- Records extracted: {report.get('records_extracted')}",
        f"- Records accepted: {report.get('records_accepted')}",
        f"- Chunks created: {report.get('chunks_created')}",
        f"- Embedding model: {report.get('embedding_model')}",
        f"- Vector size: {report.get('vector_size')}",
        f"- Qdrant collection: {report.get('qdrant_collection_name')}",
        f"- Qdrant points: {report.get('qdrant_points_count')}",
        f"- Snapshot: {report.get('qdrant_snapshot_path')}",
        f"- Embedded points backup: {report.get('embedded_points_path')}",
        "",
        "## Next Steps",
        "",
        *[f"- {step}" for step in report.get("next_steps") or []],
    ]
    return "\n".join(lines) + "\n"


def print_restore_instructions(config: PipelineConfig) -> None:
    print(
        f"""
Windows PowerShell restore example:

curl.exe -X POST "http://localhost:6333/collections/{config.collection_name}/snapshots/upload?priority=snapshot" `
     -H "Content-Type: multipart/form-data" `
     -F "snapshot=@C:\\Users\\<YOUR_USER>\\Downloads\\<SNAPSHOT_FILE>.snapshot"

Then set local .env:

QDRANT_COLLECTION_NAME={config.collection_name}

Restart Streamlit:

uv run streamlit run app/streamlit_app.py

Validation:

uv run python scripts/test_retrieval.py "Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)"
uv run python scripts/test_retrieval.py "Tell me about WE Business Value 175"
"""
    )


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.lower().strip()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Colab full build pipeline for Telecom Egypt RAG artifacts.")
    parser.add_argument("--stage", default="all", choices=["setup", "scrape", "build-kb", "build-chunks", "build-bm25", "ollama", "qdrant", "embed", "snapshot", "report", "restore-instructions", "all"])
    parser.add_argument("--workspace-dir", type=Path, default=Path(os.getenv("WORKSPACE_DIR", DEFAULT_WORKSPACE_DIR)))
    parser.add_argument("--repo-dir", type=Path, default=Path(os.getenv("REPO_DIR", PROJECT_ROOT)))
    parser.add_argument("--max-pages-per-section", type=int, default=5)
    parser.add_argument("--full", action="store_true", help="Run full mode with no per-section page cap.")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--overwrite-processed", type=parse_bool, default=False)
    parser.add_argument("--force-refetch", type=parse_bool, default=False)
    parser.add_argument("--force-reembed", type=parse_bool, default=False)
    parser.add_argument("--dynamic", type=parse_bool, default=False)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--qdrant-image", default=DEFAULT_QDRANT_IMAGE)
    parser.add_argument("--enable-mobile", type=parse_bool, default=False)
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> PipelineConfig:
    sections = default_sections()
    if args.enable_mobile:
        sections["mobile"].enabled = True
    return PipelineConfig(
        workspace_dir=args.workspace_dir,
        repo_dir=args.repo_dir,
        sections=sections,
        max_pages_per_section=None if args.full else args.max_pages_per_section,
        concurrency=args.concurrency,
        delay_seconds=args.delay_seconds,
        overwrite_processed=args.overwrite_processed,
        force_refetch=args.force_refetch,
        force_reembed=args.force_reembed,
        dynamic=args.dynamic,
        collection_name=args.collection_name,
        embedding_model=args.embedding_model,
        qdrant_image=args.qdrant_image,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = build_config(args)
    if args.stage == "setup":
        ensure_workspace(config)
    elif args.stage == "scrape":
        asyncio.run(scrape_sections(config))
    elif args.stage == "build-kb":
        build_unified_kb(config)
    elif args.stage == "build-chunks":
        build_chunks(config)
    elif args.stage == "build-bm25":
        build_bm25(config)
    elif args.stage == "ollama":
        install_and_start_ollama(config)
    elif args.stage == "qdrant":
        start_qdrant_docker(config)
    elif args.stage == "embed":
        generate_embeddings_and_upsert(config)
    elif args.stage == "snapshot":
        create_qdrant_snapshot(config)
    elif args.stage == "report":
        write_final_report(config)
    elif args.stage == "restore-instructions":
        print_restore_instructions(config)
    elif args.stage == "all":
        ensure_workspace(config)
        asyncio.run(scrape_sections(config))
        build_unified_kb(config)
        build_chunks(config)
        build_bm25(config)
        install_and_start_ollama(config)
        start_qdrant_docker(config)
        generate_embeddings_and_upsert(config)
        create_qdrant_snapshot(config)
        write_final_report(config)
        print_restore_instructions(config)


if __name__ == "__main__":
    main()
