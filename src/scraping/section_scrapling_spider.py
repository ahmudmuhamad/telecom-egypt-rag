from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from scrapling import AsyncFetcher

from src.scraping.section_parser import (
    PageContext,
    normalize_whitespace,
    parse_section_page,
    stable_hash,
)
from src.scraping.section_post_processor import post_process_records, write_jsonl
from src.scraping.section_quality import write_quality_report


COMMON_DENY_PATTERNS = [
    "login",
    "signin",
    "javascript:",
    "mailto:",
    "tel:",
    "facebook",
    "twitter",
    "linkedin",
    "youtube",
    "shop.te.eg",
    "my.te.eg",
    "ir.te.eg",
    "csr.te.eg",
]


@dataclass(frozen=True)
class SectionConfig:
    name: str
    category: str
    customer_segment: str
    seeds: tuple[str, ...]
    allow_patterns: tuple[str, ...]
    deny_patterns: tuple[str, ...] = tuple(COMMON_DENY_PATTERNS)


@dataclass(frozen=True)
class UrlTask:
    url: str
    page_kind: str
    listing_url: str
    source_url: str


@dataclass
class FetchResult:
    task: UrlTask
    html: str
    final_url: str
    raw_html_path: Path
    status: int | None
    from_cache: bool = False


SECTION_CONFIGS: dict[str, SectionConfig] = {
    "corporate_sustainability": SectionConfig(
        name="corporate_sustainability",
        category="corporate_sustainability",
        customer_segment="corporate",
        seeds=(
            "https://te.eg/en/Corporate-Sustainability/",
            "https://te.eg/en/web/guest/corporate-sustainability/sustainability",
            "https://te.eg/en/web/guest/corporate-sustainability/climate-change",
            "https://te.eg/en/web/guest/corporate-sustainability/corporate-quality",
            "https://te.eg/Corporate-Sustainability/",
            "https://te.eg/Corporate-Sustainability/Sustainability",
            "https://te.eg/Corporate-Sustainability/climate-change",
            "https://te.eg/Corporate-Sustainability/corporate-quality",
        ),
        allow_patterns=(
            "Corporate-Sustainability",
            "corporate-sustainability",
            "sustainability",
            "climate-change",
            "corporate-quality",
        ),
    ),
    "about_te": SectionConfig(
        name="about_te",
        category="about_te",
        customer_segment="corporate",
        seeds=(
            "https://te.eg/en/about-te/",
            "https://te.eg/en/about-te/board-of-directors",
            "https://te.eg/en/about-te/management-team",
            "https://te.eg/en/about-te/te-museum",
            "https://te.eg/en/about-te/history",
            "https://te.eg/en/about-te/awards",
            "https://te.eg/en/about-te/corporate-strategy",
            "https://te.eg/en/about-te/press-releases",
            "https://te.eg/en/about-te/tv-ads",
            "https://te.eg/en/about-te/careers-and-training",
            "https://te.eg/en/about-te/contact-us",
            "https://te.eg/about-te/",
            "https://te.eg/about-te/board-of-directors",
            "https://te.eg/about-te/management-team",
            "https://te.eg/about-te/te-museum",
            "https://te.eg/about-te/history",
            "https://te.eg/about-te/awards",
            "https://te.eg/about-te/corporate-strategy",
            "https://te.eg/about-te/press-releases",
            "https://te.eg/about-te/tv-ads",
            "https://te.eg/about-te/careers-and-training",
            "https://te.eg/about-te/contact-us",
        ),
        allow_patterns=(
            "/about-te",
            "about-te",
            "board-of-directors",
            "management-team",
            "te-museum",
            "history",
            "awards",
            "corporate-strategy",
            "press-releases",
            "tv-ads",
            "careers-and-training",
            "contact-us",
        ),
    ),
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.lower().strip()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}")


def safe_filename(url: str) -> str:
    parts = urlsplit(url)
    raw = f"{parts.netloc}_{parts.path}_{parts.query}".strip("/").replace("/", "_")
    raw = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("_")
    return f"{raw[:120]}_{stable_hash(url, 10)}.html"


def raw_html_path(output_dir: Path, section: str, page_kind: str, url: str) -> Path:
    return output_dir / "01_raw_html" / section / page_kind / safe_filename(url)


def response_html(response: Any) -> str:
    html = getattr(response, "html_content", None)
    if html is None:
        html = getattr(response, "text", "")
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    return str(html or "")


def is_allowed_url(url: str, config: SectionConfig) -> bool:
    lowered = url.lower()
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return False
    if parts.netloc.lower() not in {"te.eg", "www.te.eg"}:
        return False
    if any(pattern.lower() in lowered for pattern in config.deny_patterns):
        return False
    return any(pattern.lower() in lowered for pattern in config.allow_patterns)


def extract_links(html: str, base_url: str, config: SectionConfig) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()
    for node in soup.select("a[href]"):
        href = normalize_whitespace(node.get("href"))
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(base_url, href).split("#", 1)[0]
        if is_allowed_url(full_url, config) and full_url not in seen:
            seen.add(full_url)
            links.append(full_url)
    return links


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


class SectionScraplingSpider:
    def __init__(
        self,
        *,
        config: SectionConfig,
        output_dir: Path,
        concurrency: int,
        delay: float,
        cache: bool,
        resume: bool,
        max_pages: int | None,
        force: bool,
    ) -> None:
        self.config = config
        self.output_dir = output_dir
        self.concurrency = max(1, concurrency)
        self.delay = max(0.0, delay)
        self.cache = cache
        self.resume = resume
        self.max_pages = max_pages
        self.force = force
        self.user_agent = "TelecomEgyptRAGSectionScraper/1.0 (+respectful section crawl)"
        self.robots = RobotsCache(self.user_agent)
        self.failed_urls: list[dict[str, Any]] = []
        self.fetched_results: list[FetchResult] = []
        self.pages_seen = 0
        self.last_request_at = 0.0
        self.throttle_lock = asyncio.Lock()
        self.checkpoint_path = (
            self.output_dir / "00_crawl_checkpoints" / f"{self.config.name}_checkpoint.json"
        )
        self.checkpoint: dict[str, Any] = {"fetched": {}, "failed_urls": []}

    async def run(self) -> dict[str, Any]:
        started_at = utc_now_iso()
        self.ensure_directories()
        self.load_checkpoint()
        seed_tasks = [
            UrlTask(url=url, page_kind="listing_pages", listing_url=url, source_url=url)
            for url in self.config.seeds
        ]
        seed_results = await self.fetch_many(seed_tasks)
        detail_tasks = self.discover_detail_tasks(seed_results, seed_tasks)
        detail_results = await self.fetch_many(detail_tasks)
        records = self.extract_records([*seed_results, *detail_results])
        return self.write_outputs(records, started_at)

    def ensure_directories(self) -> None:
        for relative in (
            "00_crawl_checkpoints",
            f"01_raw_html/{self.config.name}/listing_pages",
            f"01_raw_html/{self.config.name}/detail_pages",
            f"02_extracted_records/{self.config.name}",
            f"03_clean_records_by_category/{self.config.name}",
            f"04_quality_reports/{self.config.name}",
        ):
            (self.output_dir / relative).mkdir(parents=True, exist_ok=True)
        Path("data/processed", self.config.name).mkdir(parents=True, exist_ok=True)

    def load_checkpoint(self) -> None:
        if not self.resume or not self.checkpoint_path.exists():
            return
        try:
            self.checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.failed_urls = list(self.checkpoint.get("failed_urls") or [])
        except json.JSONDecodeError:
            self.checkpoint = {"fetched": {}, "failed_urls": []}

    def save_checkpoint(self) -> None:
        self.checkpoint["failed_urls"] = self.failed_urls
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path.write_text(
            json.dumps(self.checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    async def fetch_many(self, tasks: list[UrlTask]) -> list[FetchResult]:
        results: list[FetchResult] = []
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_task(task: UrlTask) -> None:
            async with semaphore:
                if self.max_pages is not None and self.pages_seen >= self.max_pages:
                    return
                self.pages_seen += 1
                result = await self.fetch_one(task)
                if result is not None:
                    results.append(result)

        await asyncio.gather(*(run_task(task) for task in tasks))
        self.save_checkpoint()
        self.fetched_results.extend(results)
        return results

    async def throttle(self) -> None:
        if self.delay <= 0:
            return
        async with self.throttle_lock:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
            self.last_request_at = time.monotonic()

    def checkpoint_result(self, task: UrlTask) -> FetchResult | None:
        entry = self.checkpoint.get("fetched", {}).get(task.url)
        if not entry or self.force:
            return None
        raw_path = Path(entry.get("raw_html_path", ""))
        if not raw_path.exists():
            return None
        return FetchResult(
            task=task,
            html=raw_path.read_text(encoding="utf-8", errors="replace"),
            final_url=entry.get("final_url") or task.url,
            raw_html_path=raw_path,
            status=entry.get("status"),
            from_cache=True,
        )

    async def fetch_one(self, task: UrlTask) -> FetchResult | None:
        checkpoint_result = self.checkpoint_result(task)
        if checkpoint_result is not None:
            return checkpoint_result

        raw_path = raw_html_path(self.output_dir, self.config.name, task.page_kind, task.url)
        if self.cache and raw_path.exists() and not self.force:
            return FetchResult(
                task=task,
                html=raw_path.read_text(encoding="utf-8", errors="replace"),
                final_url=task.url,
                raw_html_path=raw_path,
                status=200,
                from_cache=True,
            )

        if not await self.robots.allowed(task.url):
            self.record_failure(task.url, "robots.txt disallowed")
            return None

        try:
            await self.throttle()
            response = await self.static_fetch(task.url)
            html = response_html(response)
            final_url = str(getattr(response, "url", task.url))
            status = getattr(response, "status", None)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html, encoding="utf-8")
            self.checkpoint.setdefault("fetched", {})[task.url] = {
                "final_url": final_url,
                "raw_html_path": str(raw_path),
                "status": status,
            }
            return FetchResult(task, html, final_url, raw_path, status)
        except Exception as exc:
            self.record_failure(task.url, f"{type(exc).__name__}: {exc}")
            return None

    async def static_fetch(self, url: str) -> Any:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            "User-Agent": self.user_agent,
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

    def record_failure(self, url: str, reason: str) -> None:
        self.failed_urls.append({"url": url, "reason": reason})

    def discover_detail_tasks(
        self,
        seed_results: list[FetchResult],
        seed_tasks: list[UrlTask],
    ) -> list[UrlTask]:
        seen = {task.url for task in seed_tasks}
        tasks: list[UrlTask] = []
        for result in seed_results:
            for link in extract_links(result.html, result.final_url, self.config):
                if link in seen:
                    continue
                seen.add(link)
                tasks.append(
                    UrlTask(
                        url=link,
                        page_kind="detail_pages",
                        listing_url=result.final_url,
                        source_url=link,
                    )
                )
        return tasks

    def extract_records(self, results: list[FetchResult]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for result in results:
            context = PageContext(
                section=self.config.name,
                category=self.config.category,
                customer_segment=self.config.customer_segment,
                source_url=result.task.source_url,
                listing_url=result.task.listing_url,
                final_url=result.final_url,
                raw_html_path=str(result.raw_html_path),
                page_kind=result.task.page_kind,
                from_cache=result.from_cache,
            )
            try:
                records.extend(parse_section_page(result.html, context))
            except Exception as exc:
                self.record_failure(result.task.url, f"parse {type(exc).__name__}: {exc}")
        return records

    def write_outputs(self, extracted_records: list[dict[str, Any]], started_at: str) -> dict[str, Any]:
        section = self.config.name
        extracted_path = self.output_dir / "02_extracted_records" / section / f"{section}.jsonl"
        clean_path = self.output_dir / "03_clean_records_by_category" / section / f"{section}.jsonl"
        post_path = (
            self.output_dir
            / "03_clean_records_by_category"
            / section
            / f"{section}_post_processed.jsonl"
        )
        final_processed_path = Path("data/processed") / section / f"{section}_post_processed.jsonl"
        report_path = self.output_dir / "04_quality_reports" / section / f"{section}_quality_report.csv"
        summary_path = self.output_dir / "04_quality_reports" / section / f"{section}_summary.json"

        write_jsonl(extracted_path, extracted_records)
        processed_records = post_process_records(extracted_records)
        write_jsonl(clean_path, processed_records)
        write_jsonl(post_path, processed_records)
        write_jsonl(final_processed_path, processed_records)
        output_files = {
            "extracted_path": str(extracted_path),
            "clean_path": str(clean_path),
            "post_processed_path": str(post_path),
            "final_processed_path": str(final_processed_path),
            "quality_csv": str(report_path),
            "summary_json": str(summary_path),
        }
        summary = write_quality_report(
            processed_records,
            report_path,
            summary_path,
            section=section,
            total_urls=len(self.checkpoint.get("fetched", {})) + len(self.failed_urls),
            pages_fetched=len(self.fetched_results),
            failed_urls=self.failed_urls,
            started_at=started_at,
            completed_at=utc_now_iso(),
            output_files=output_files,
        )
        return {**output_files, "summary": summary}


def output_dir_for_section(section: str) -> Path:
    return Path(f"data/scrape_{section}_scrapling_v1")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape section-specific Telecom Egypt official pages with Scrapling."
    )
    parser.add_argument("sections", nargs="+", choices=sorted(SECTION_CONFIGS))
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--cache", type=parse_bool, default=True)
    parser.add_argument("--resume", type=parse_bool, default=True)
    parser.add_argument("--force", type=parse_bool, default=False)
    return parser.parse_args(argv)


async def run_section(section: str, args: argparse.Namespace) -> dict[str, Any]:
    spider = SectionScraplingSpider(
        config=SECTION_CONFIGS[section],
        output_dir=output_dir_for_section(section),
        concurrency=args.concurrency,
        delay=args.delay,
        cache=args.cache,
        resume=args.resume,
        max_pages=args.max_pages,
        force=args.force,
    )
    return await spider.run()


async def async_main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    results = {}
    for section in args.sections:
        results[section] = await run_section(section, args)
    return results


def main(argv: list[str] | None = None) -> None:
    results = asyncio.run(async_main(argv))
    for section, result in results.items():
        summary = result["summary"]
        print(f"{section} Scrapling scrape complete")
        print(f"Total records: {summary['total_records']}")
        print(f"Accepted records: {summary['accepted_records']}")
        print(f"Rejected records: {summary['rejected_records']}")
        print(f"Pages fetched: {summary['fetched_urls']}")
        print(f"Failed URLs: {summary['failed_urls']}")
        print(f"Processed JSONL: {result['final_processed_path']}")
        print(f"Quality CSV: {result['quality_csv']}")
        print(f"Summary JSON: {result['summary_json']}")


if __name__ == "__main__":
    main(sys.argv[1:])
