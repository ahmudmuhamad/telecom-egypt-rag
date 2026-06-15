from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
import time
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup


DEFAULT_SEEDS = (
    "https://te.eg/en/",
    "https://te.eg/ar/",
    "https://te.eg/en/personal",
    "https://te.eg/ar/personal",
    "https://te.eg/en/business",
    "https://te.eg/ar/business",
)
PUBLIC_HOSTS = {"te.eg", "www.te.eg"}
DENY_URL_PARTS = (
    "/login",
    "/logout",
    "/myaccount",
    "/account",
    "/checkout",
    "/cart",
    "/payment",
    "/pay",
    "/billpayment",
    "/selfcare",
    "/o/",
    "/combo",
    "/api/",
    "/c/portal",
    "javascript:",
    "mailto:",
    "tel:",
)
DENY_EXTENSIONS = (
    ".css",
    ".js",
    ".json",
    ".xml",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".zip",
    ".rar",
    ".mp4",
    ".mp3",
)
NOISE_LINE_RE = re.compile(
    r"^(home|personal|business|about us|contact us|search|login|my account|"
    r"english|العربية|facebook|twitter|instagram|youtube|linkedin)$",
    re.IGNORECASE,
)
ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
USSD_RE = re.compile(r"(?<!\w)(?:\*\d{2,6}(?:\*\d{1,6})*#?|#\d{2,6}\*?)(?!\w)")
PRICE_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:EGP|LE|L\.E|جنيه|ج\.م|جم|PT|قرش|قروش)",
    re.IGNORECASE,
)
QUOTA_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:GB|G\.B|MB|M\.B|جيجابايت|جيجا|ميجابايت|ميجا)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    html: str
    status_code: int
    raw_html_path: Path
    from_cache: bool = False


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_fragment(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def normalize_url(url: str) -> str:
    parts = urlsplit(strip_fragment(url))
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def canonical_url(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    path = re.sub(r"/(en|ar)(/|$)", "/", parts.path, count=1, flags=re.IGNORECASE)
    path = re.sub(r"/{2,}", "/", path)
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def safe_filename(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path}_{parts.query}".strip("/")
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw.replace("/", "_")).strip("_")
    return f"{raw[:120]}_{stable_hash(url, 10)}.html"


def language_from_url_or_text(url: str, text: str) -> str:
    if "/ar/" in url:
        return "ar"
    if "/en/" in url:
        return "en"
    arabic = len(ARABIC_RE.findall(text[:4000]))
    latin = len(re.findall(r"[A-Za-z]", text[:4000]))
    if arabic > max(30, latin):
        return "ar"
    if latin > 30:
        return "en"
    return "unknown"


def category_from_url(url: str) -> str:
    lowered = url.lower()
    if "/business" in lowered:
        return "business"
    if "/support" in lowered or "/help" in lowered:
        return "support"
    if "/offer" in lowered or "/offers" in lowered:
        return "offers"
    if "/branch" in lowered or "stores" in lowered:
        return "branches"
    if "/mobile" in lowered:
        return "mobile"
    if "/devices" in lowered or "/w/" in lowered:
        return "public_site"
    if "/personal" in lowered:
        return "personal"
    return "public_site"


def record_type_from_content(url: str, text: str) -> str:
    lowered = f"{url} {text[:2000]}".lower()
    if USSD_RE.search(text):
        return "service_detail"
    if PRICE_RE.search(text) or QUOTA_RE.search(text):
        return "package_or_offer"
    if "faq" in lowered or "question" in lowered or "سؤال" in text[:2000]:
        return "faq"
    if "/branch" in lowered or "store locator" in lowered:
        return "branch_info"
    return "public_page"


def remove_noise_nodes(soup: BeautifulSoup) -> None:
    selectors = (
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
    )
    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()


def visible_lines(soup: BeautifulSoup, max_lines: int = 240) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in soup.get_text("\n", strip=True).splitlines():
        line = normalize_whitespace(raw)
        key = line.casefold()
        if not line or key in seen or NOISE_LINE_RE.match(line):
            continue
        if len(line) <= 2 and not line.isdigit():
            continue
        seen.add(key)
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def extract_title(soup: BeautifulSoup, lines: list[str]) -> str:
    selectors = ("h1", "meta[property='og:title']", "title", "h2")
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        value = node.get("content", "") if node.name == "meta" else node.get_text(" ", strip=True)
        value = normalize_whitespace(value)
        value = re.sub(r"\s*-\s*Telecom Egypt\s*$", "", value, flags=re.IGNORECASE)
        if value:
            return value
    return lines[0] if lines else "Untitled public page"


def extract_description(soup: BeautifulSoup, lines: list[str]) -> str:
    node = soup.select_one("meta[name='description'], meta[property='og:description']")
    if node:
        value = normalize_whitespace(node.get("content", ""))
        if value:
            return value
    for line in lines:
        if len(line) >= 40:
            return line
    return ""


def clean_html_to_record(result: FetchResult) -> dict[str, Any] | None:
    soup = BeautifulSoup(result.html, "lxml")
    remove_noise_nodes(soup)
    body = soup.select_one("main") or soup.select_one("[role='main']") or soup.body or soup
    lines = visible_lines(body)
    if not lines:
        return None
    title = extract_title(soup, lines)
    description = extract_description(soup, lines)
    content_lines = [line for line in lines if line not in {title, description}]
    content_parts = [f"Title: {title}"]
    if description:
        content_parts.append(f"Description: {description}")
    content_parts.append("Details:")
    content_parts.extend(content_lines[:120])
    content = "\n".join(content_parts).strip()
    if len(content) < 120:
        return None

    language = language_from_url_or_text(result.final_url, content)
    category = category_from_url(result.final_url)
    ussd_codes = sorted(set(USSD_RE.findall(content)))
    prices = sorted(set(PRICE_RE.findall(content)))
    quotas = sorted(set(QUOTA_RE.findall(content)))
    flags = ["public_site_scrape"]
    if result.from_cache:
        flags.append("from_cache")
    if len(content) < 300:
        flags.append("short_content")
    if not description:
        flags.append("missing_meta_description")
    record_id = stable_hash(f"{canonical_url(result.final_url)}\n{title}\n{content}", length=64)
    return {
        "record_id": record_id,
        "doc_id": stable_hash(canonical_url(result.final_url), length=64),
        "category": category,
        "record_type": record_type_from_content(result.final_url, content),
        "language": language,
        "source_name": "Telecom Egypt",
        "source_type": "official_website",
        "source_url": result.url,
        "final_url": result.final_url,
        "canonical_url": canonical_url(result.final_url),
        "citation_url": result.final_url,
        "title": title,
        "section_title": title,
        "description": description,
        "content": content,
        "search_aliases": [title],
        "ussd_codes": ussd_codes,
        "prices": prices,
        "quotas": quotas,
        "raw_html_path": str(result.raw_html_path),
        "last_scraped": utc_now_iso(),
        "quality_score": quality_score(content, result.final_url, title),
        "quality_flags": flags,
        "is_accepted": True,
    }


def quality_score(content: str, citation_url: str, title: str) -> float:
    score = 0.5
    if citation_url:
        score += 0.15
    if title and title != "Untitled public page":
        score += 0.15
    if len(content) >= 300:
        score += 0.1
    if USSD_RE.search(content) or PRICE_RE.search(content) or QUOTA_RE.search(content):
        score += 0.1
    return min(round(score, 3), 0.99)


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href"))
        if not href:
            continue
        candidate = normalize_url(urljoin(base_url, href))
        if is_allowed_public_url(candidate) and candidate not in seen:
            seen.add(candidate)
            links.append(candidate)
    return links


def is_allowed_public_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.netloc.lower() not in PUBLIC_HOSTS:
        return False
    lowered = url.lower()
    if any(part in lowered for part in DENY_URL_PARTS):
        return False
    if any(parts.path.lower().endswith(ext) for ext in DENY_EXTENSIONS):
        return False
    return True


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self.user_agent = user_agent
        self.parsers: dict[str, RobotFileParser | None] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self.parsers:
            self.parsers[base] = await self._load_parser(base)
        parser = self.parsers[base]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    async def _load_parser(self, base: str) -> RobotFileParser | None:
        parser = RobotFileParser(f"{base}/robots.txt")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(
                    f"{base}/robots.txt",
                    headers={"User-Agent": self.user_agent},
                )
            if response.status_code >= 400:
                return None
            parser.parse(response.text.splitlines())
            return parser
        except Exception:
            return None


class PublicSiteSpider:
    def __init__(
        self,
        *,
        output_dir: Path,
        seeds: list[str],
        max_pages: int,
        concurrency: int,
        delay: float,
        cache: bool,
        resume: bool,
        force: bool,
    ) -> None:
        self.output_dir = output_dir
        self.seeds = [normalize_url(seed) for seed in seeds if is_allowed_public_url(seed)]
        self.max_pages = max_pages
        self.concurrency = max(1, concurrency)
        self.delay = max(0.0, delay)
        self.cache = cache
        self.resume = resume
        self.force = force
        self.user_agent = "TelecomEgyptRAGPublicCrawler/1.0 (+local quality review)"
        self.robots = RobotsCache(self.user_agent)
        self.checkpoint_path = self.output_dir / "00_crawl_checkpoints" / "public_site_checkpoint.json"
        self.checkpoint: dict[str, Any] = {"fetched": {}, "failed_urls": [], "queued": []}
        self.failed_urls: list[dict[str, str]] = []
        self.last_request_at = 0.0
        self.throttle_lock = asyncio.Lock()

    async def run(self) -> dict[str, Any]:
        self.ensure_dirs()
        self.load_checkpoint()
        fetched = await self.crawl()
        records = [record for result in fetched if (record := clean_html_to_record(result))]
        return self.write_outputs(records, fetched)

    def ensure_dirs(self) -> None:
        for relative in (
            "00_crawl_checkpoints",
            "01_raw_html/public_site",
            "02_extracted_records/public_site",
            "03_clean_records_by_category/public_site",
            "04_quality_reports/public_site",
        ):
            (self.output_dir / relative).mkdir(parents=True, exist_ok=True)
        Path("data/processed/public_site").mkdir(parents=True, exist_ok=True)

    def load_checkpoint(self) -> None:
        if not self.resume or not self.checkpoint_path.exists():
            return
        try:
            self.checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.failed_urls = list(self.checkpoint.get("failed_urls") or [])
        except json.JSONDecodeError:
            self.checkpoint = {"fetched": {}, "failed_urls": [], "queued": []}

    def save_checkpoint(self, queued: list[str]) -> None:
        self.checkpoint["failed_urls"] = self.failed_urls
        self.checkpoint["queued"] = queued
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(
            json.dumps(self.checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    async def crawl(self) -> list[FetchResult]:
        fetched_results: list[FetchResult] = []
        seen = set(self.checkpoint.get("fetched") or {})
        queued = deque(self.checkpoint.get("queued") or self.seeds)
        queued_seen = set(queued)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def worker() -> None:
            while len(fetched_results) < self.max_pages:
                try:
                    url = queued.popleft()
                except IndexError:
                    return
                if url in seen and not self.force:
                    cached = self.result_from_checkpoint(url)
                    if cached is not None:
                        fetched_results.append(cached)
                        for link in extract_links(cached.html, cached.final_url):
                            if link not in seen and link not in queued_seen:
                                queued.append(link)
                                queued_seen.add(link)
                    continue
                async with semaphore:
                    result = await self.fetch_one(url)
                if result is None:
                    continue
                seen.add(url)
                fetched_results.append(result)
                for link in extract_links(result.html, result.final_url):
                    if link not in seen and link not in queued_seen:
                        queued.append(link)
                        queued_seen.add(link)
                self.save_checkpoint(list(queued))

        await asyncio.gather(*(worker() for _ in range(self.concurrency)))
        self.save_checkpoint(list(queued))
        return fetched_results

    def result_from_checkpoint(self, url: str) -> FetchResult | None:
        entry = (self.checkpoint.get("fetched") or {}).get(url)
        if not entry:
            return None
        path = Path(entry.get("raw_html_path") or "")
        if not path.exists():
            return None
        return FetchResult(
            url=url,
            final_url=entry.get("final_url") or url,
            html=path.read_text(encoding="utf-8", errors="replace"),
            status_code=int(entry.get("status_code") or 200),
            raw_html_path=path,
            from_cache=True,
        )

    async def throttle(self) -> None:
        if self.delay <= 0:
            return
        async with self.throttle_lock:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self.last_request_at = time.monotonic()

    async def fetch_one(self, url: str) -> FetchResult | None:
        raw_path = self.output_dir / "01_raw_html" / "public_site" / safe_filename(url)
        if self.cache and raw_path.exists() and not self.force:
            html = raw_path.read_text(encoding="utf-8", errors="replace")
            return FetchResult(url, url, html, 200, raw_path, from_cache=True)
        if not await self.robots.allowed(url):
            self.failed_urls.append({"url": url, "reason": "robots.txt disallowed"})
            return None
        try:
            await self.throttle()
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                        "User-Agent": self.user_agent,
                    },
                )
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                self.failed_urls.append({"url": url, "reason": f"non-html {content_type}"})
                return None
            html = response.text
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html, encoding="utf-8")
            final_url = normalize_url(str(response.url))
            self.checkpoint.setdefault("fetched", {})[url] = {
                "final_url": final_url,
                "raw_html_path": str(raw_path),
                "status_code": response.status_code,
            }
            return FetchResult(url, final_url, html, response.status_code, raw_path)
        except Exception as exc:
            self.failed_urls.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})
            return None

    def write_outputs(self, records: list[dict[str, Any]], fetched: list[FetchResult]) -> dict[str, Any]:
        extracted_path = self.output_dir / "02_extracted_records/public_site/public_site.jsonl"
        clean_path = self.output_dir / "03_clean_records_by_category/public_site/public_site_post_processed.jsonl"
        final_path = Path("data/processed/public_site/public_site_post_processed.jsonl")
        report_path = self.output_dir / "04_quality_reports/public_site/public_site_quality_report.csv"
        summary_path = self.output_dir / "04_quality_reports/public_site/public_site_summary.json"
        write_jsonl(extracted_path, records)
        write_jsonl(clean_path, records)
        write_jsonl(final_path, records)
        summary = write_quality_report(records, report_path, summary_path, len(fetched), self.failed_urls)
        return {
            "extracted_path": str(extracted_path),
            "clean_path": str(clean_path),
            "final_processed_path": str(final_path),
            "report_path": str(report_path),
            "summary_path": str(summary_path),
            "summary": summary,
        }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_quality_report(
    records: list[dict[str, Any]],
    report_path: Path,
    summary_path: Path,
    pages_fetched: int,
    failed_urls: list[dict[str, str]],
) -> dict[str, Any]:
    columns = [
        "record_id",
        "title",
        "category",
        "record_type",
        "language",
        "citation_url",
        "quality_score",
        "quality_flags",
        "content_length",
        "has_code",
        "has_price",
        "has_quota",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "record_id": record.get("record_id"),
                    "title": record.get("title"),
                    "category": record.get("category"),
                    "record_type": record.get("record_type"),
                    "language": record.get("language"),
                    "citation_url": record.get("citation_url"),
                    "quality_score": record.get("quality_score"),
                    "quality_flags": ";".join(record.get("quality_flags") or []),
                    "content_length": len(record.get("content") or ""),
                    "has_code": bool(record.get("ussd_codes")),
                    "has_price": bool(record.get("prices")),
                    "has_quota": bool(record.get("quotas")),
                }
            )
    summary = {
        "total_records": len(records),
        "accepted_records": len(records),
        "pages_fetched": pages_fetched,
        "failed_urls": failed_urls,
        "counts_by_category": dict(Counter(record.get("category") for record in records)),
        "counts_by_record_type": dict(Counter(record.get("record_type") for record in records)),
        "counts_by_language": dict(Counter(record.get("language") for record in records)),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape public WE/Telecom Egypt pages locally.")
    parser.add_argument("--seeds", nargs="*", default=list(DEFAULT_SEEDS))
    parser.add_argument("--output-dir", type=Path, default=Path("data/scrape_public_site_v1"))
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--cache", type=lambda value: value.lower() == "true", default=True)
    parser.add_argument("--resume", type=lambda value: value.lower() == "true", default=True)
    parser.add_argument("--force", type=lambda value: value.lower() == "true", default=False)
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    spider = PublicSiteSpider(
        output_dir=args.output_dir,
        seeds=args.seeds,
        max_pages=args.max_pages,
        concurrency=args.concurrency,
        delay=args.delay,
        cache=args.cache,
        resume=args.resume,
        force=args.force,
    )
    return await spider.run()


def main(argv: list[str] | None = None) -> None:
    result = asyncio.run(async_main(argv))
    summary = result["summary"]
    print("Public WE/Telecom Egypt scrape complete")
    print(f"Pages fetched: {summary['pages_fetched']}")
    print(f"Records: {summary['total_records']}")
    print(f"Failed URLs: {len(summary['failed_urls'])}")
    print(f"Processed JSONL: {result['final_processed_path']}")
    print(f"Quality CSV: {result['report_path']}")


if __name__ == "__main__":
    main()
