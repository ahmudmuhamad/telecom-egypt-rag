from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from scrapling import AsyncFetcher

from src.scraping.mobile_parser import (
    PageContext,
    extract_links,
    infer_mobile_category,
    parse_mobile_page,
    raw_html_path,
)
from src.scraping.mobile_post_processor import post_process_records, write_jsonl
from src.scraping.mobile_quality import write_quality_report


ENGLISH_URL_PLAN = (
    ("https://te.eg/en/personal/mobile", "unknown", "listing_pages"),
    ("https://te.eg/en/web/guest/personal/mobile/prepaid", "prepaid", "listing_pages"),
    ("https://te.eg/en/personal/mobile/prepaid/12pt", "prepaid", "detail_pages"),
    ("https://te.eg/en/web/guest/personal/mobile/control", "control_plans", "listing_pages"),
    ("https://te.eg/en/personal/mobile/control-we-mix", "control_plans", "detail_pages"),
    ("https://te.eg/en/personal/mobile/control/super-kix", "control_plans", "detail_pages"),
    ("https://te.eg/en/w/super-kix-25", "control_plans", "detail_pages"),
    ("https://te.eg/en/personal/mobile/control-tazbeet", "control_plans", "detail_pages"),
    ("https://te.eg/en/web/guest/w/we-club-50", "control_plans", "detail_pages"),
    ("https://te.eg/en/web/guest/personal/mobile/we-gold", "postpaid", "detail_pages"),
    (
        "https://te.eg/en/personal/mobile/nitro-mobile-internet",
        "mobile_internet",
        "listing_pages",
    ),
    (
        "https://te.eg/en/web/guest/personal/mobile/nitro-mobile-internet/prime",
        "mobile_internet",
        "detail_pages",
    ),
    (
        "https://te.eg/en/personal/mobile/nitro-mobile-internet/nitro-extra",
        "mobile_internet",
        "detail_pages",
    ),
    ("https://te.eg/en/nitro-extra?filterBy=streaming", "mobile_internet", "detail_pages"),
    (
        "https://te.eg/en/web/guest/w/nitro-mifi-260?pid=&qid=Nitro%20MiFi&cid=609379",
        "mobile_internet",
        "detail_pages",
    ),
    (
        "https://te.eg/en/web/guest/personal/services/mobile-call-services",
        "value_added_services",
        "listing_pages",
    ),
)


@dataclass(frozen=True)
class UrlTask:
    url: str
    language: str
    mobile_category: str
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
    dynamic_fetch_used: bool = False


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    lowered = value.lower().strip()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected boolean value, got {value!r}")


def swap_language(url: str, language: str) -> str:
    if "/en/" in url:
        return url.replace("/en/", f"/{language}/", 1)
    if "/ar/" in url:
        return url.replace("/ar/", f"/{language}/", 1)
    return url


def build_url_plan(languages: list[str]) -> list[UrlTask]:
    tasks: list[UrlTask] = []
    seen: set[str] = set()
    for language in languages:
        for url, category, page_kind in ENGLISH_URL_PLAN:
            candidate = swap_language(url, language)
            if candidate in seen:
                continue
            seen.add(candidate)
            tasks.append(
                UrlTask(
                    url=candidate,
                    language=language,
                    mobile_category=category,
                    page_kind=page_kind,
                    listing_url=candidate if page_kind == "listing_pages" else "",
                    source_url=candidate,
                )
            )
    return tasks


def html_has_useful_content(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    return len(text) >= 200


def response_html(response: Any) -> str:
    html = getattr(response, "html_content", None)
    if html is None:
        html = getattr(response, "text", "")
    if isinstance(html, bytes):
        return html.decode("utf-8", errors="replace")
    return str(html or "")


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
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    async def _load_parser(self, base: str) -> RobotFileParser | None:
        robots_url = f"{base}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                response = await client.get(robots_url, headers={"User-Agent": self.user_agent})
            if response.status_code >= 400:
                return None
            parser.parse(response.text.splitlines())
            return parser
        except Exception:
            return None


class MobileScraplingSpider:
    def __init__(
        self,
        *,
        output_dir: Path,
        languages: list[str],
        concurrency: int,
        delay: float,
        cache: bool,
        resume: bool,
        max_pages: int | None,
        force: bool,
        dynamic: bool,
    ) -> None:
        self.output_dir = output_dir
        self.languages = languages
        self.concurrency = max(1, concurrency)
        self.delay = max(0.0, delay)
        self.cache = cache
        self.resume = resume
        self.max_pages = max_pages
        self.force = force
        self.dynamic = dynamic
        self.user_agent = "TelecomEgyptRAGMobilePOC/1.0 (+respectful research crawl)"
        self.robots = RobotsCache(self.user_agent)
        self.failed_urls: list[dict[str, Any]] = []
        self.fetched_results: list[FetchResult] = []
        self.pages_seen = 0
        self.last_request_at = 0.0
        self.throttle_lock = asyncio.Lock()
        self.checkpoint_path = (
            self.output_dir / "00_crawl_checkpoints" / "mobile_checkpoint.json"
        )
        self.checkpoint: dict[str, Any] = {"fetched": {}, "failed_urls": []}

    async def run(self) -> dict[str, Any]:
        self.ensure_directories()
        self.load_checkpoint()
        seed_tasks = build_url_plan(self.languages)
        seed_results = await self.fetch_many(seed_tasks)
        detail_tasks = self.discover_detail_tasks(seed_results, seed_tasks)
        detail_results = await self.fetch_many(detail_tasks)
        all_results = [*seed_results, *detail_results]
        records = self.extract_records(all_results)
        return self.write_outputs(records)

    def ensure_directories(self) -> None:
        for language in self.languages:
            for page_kind in ("listing_pages", "detail_pages"):
                (self.output_dir / "01_raw_html" / "mobile" / language / page_kind).mkdir(
                    parents=True, exist_ok=True
                )
        for relative in (
            "00_crawl_checkpoints",
            "02_extracted_records/mobile",
            "03_clean_records_by_category/mobile",
            "04_quality_reports/mobile",
        ):
            (self.output_dir / relative).mkdir(parents=True, exist_ok=True)
        Path("data/processed/mobile").mkdir(parents=True, exist_ok=True)

    def load_checkpoint(self) -> None:
        if not self.resume or not self.checkpoint_path.exists():
            return
        try:
            with self.checkpoint_path.open("r", encoding="utf-8") as file:
                self.checkpoint = json.load(file)
        except json.JSONDecodeError:
            self.checkpoint = {"fetched": {}, "failed_urls": []}

    def save_checkpoint(self) -> None:
        self.checkpoint["failed_urls"] = self.failed_urls
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        with self.checkpoint_path.open("w", encoding="utf-8") as file:
            json.dump(self.checkpoint, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")

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
        html = raw_path.read_text(encoding="utf-8", errors="replace")
        return FetchResult(
            task=task,
            html=html,
            final_url=entry.get("final_url") or task.url,
            raw_html_path=raw_path,
            status=entry.get("status"),
            from_cache=True,
            dynamic_fetch_used=entry.get("dynamic_fetch_used", False),
        )

    async def fetch_one(self, task: UrlTask) -> FetchResult | None:
        checkpoint_result = self.checkpoint_result(task)
        if checkpoint_result is not None:
            return checkpoint_result

        raw_path = raw_html_path(self.output_dir, task.language, task.page_kind, task.url)
        if self.cache and raw_path.exists() and not self.force:
            html = raw_path.read_text(encoding="utf-8", errors="replace")
            return FetchResult(
                task=task,
                html=html,
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
            dynamic_fetch_used = False
            if self.dynamic and not html_has_useful_content(html):
                dynamic_response = await self.dynamic_fetch(task.url)
                dynamic_html = response_html(dynamic_response)
                if html_has_useful_content(dynamic_html):
                    html = dynamic_html
                    final_url = str(getattr(dynamic_response, "url", final_url))
                    status = getattr(dynamic_response, "status", status)
                    dynamic_fetch_used = True
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(html, encoding="utf-8")
            self.checkpoint.setdefault("fetched", {})[task.url] = {
                "final_url": final_url,
                "raw_html_path": str(raw_path),
                "status": status,
                "dynamic_fetch_used": dynamic_fetch_used,
            }
            return FetchResult(
                task=task,
                html=html,
                final_url=final_url,
                raw_html_path=raw_path,
                status=status,
                dynamic_fetch_used=dynamic_fetch_used,
            )
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

    async def dynamic_fetch(self, url: str) -> Any:
        from scrapling import DynamicFetcher

        return await asyncio.to_thread(
            DynamicFetcher.fetch,
            url,
            headless=True,
            timeout=30,
        )

    def record_failure(self, url: str, reason: str) -> None:
        failure = {"url": url, "reason": reason}
        self.failed_urls.append(failure)

    def discover_detail_tasks(
        self, seed_results: list[FetchResult], seed_tasks: list[UrlTask]
    ) -> list[UrlTask]:
        seed_urls = {task.url for task in seed_tasks}
        seen = set(seed_urls)
        tasks: list[UrlTask] = []
        for result in seed_results:
            if result.task.page_kind != "listing_pages":
                continue
            for link in extract_links(result.html, result.final_url):
                if link in seen:
                    continue
                seen.add(link)
                category = infer_mobile_category(link)
                if category == "unknown":
                    continue
                tasks.append(
                    UrlTask(
                        url=link,
                        language=result.task.language,
                        mobile_category=category,
                        page_kind="detail_pages",
                        listing_url=result.final_url,
                        source_url=link,
                    )
                )
        return tasks

    def extract_records(self, results: list[FetchResult]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for result in results:
            category = result.task.mobile_category
            if category == "unknown":
                category = infer_mobile_category(result.final_url)
            context = PageContext(
                source_url=result.task.source_url,
                listing_url=result.task.listing_url or result.task.url,
                final_url=result.final_url,
                raw_html_path=str(result.raw_html_path),
                expected_language=result.task.language,
                mobile_category=category,
                page_kind=result.task.page_kind,
                dynamic_fetch_used=result.dynamic_fetch_used,
            )
            try:
                records.extend(parse_mobile_page(result.html, context))
            except Exception as exc:
                self.record_failure(result.task.url, f"parse {type(exc).__name__}: {exc}")
        return records

    def write_outputs(self, extracted_records: list[dict[str, Any]]) -> dict[str, Any]:
        extracted_path = (
            self.output_dir / "02_extracted_records" / "mobile" / "mobile.jsonl"
        )
        clean_path = self.output_dir / "03_clean_records_by_category" / "mobile" / "mobile.jsonl"
        post_path = (
            self.output_dir
            / "03_clean_records_by_category"
            / "mobile"
            / "mobile_post_processed.jsonl"
        )
        final_processed_path = Path("data/processed/mobile/mobile_post_processed.jsonl")
        report_path = (
            self.output_dir
            / "04_quality_reports"
            / "mobile"
            / "mobile_quality_report.csv"
        )
        summary_path = (
            self.output_dir / "04_quality_reports" / "mobile" / "mobile_summary.json"
        )

        write_jsonl(extracted_path, extracted_records)
        processed_records = post_process_records(extracted_records)
        write_jsonl(clean_path, processed_records)
        write_jsonl(post_path, processed_records)
        write_jsonl(final_processed_path, processed_records)
        summary = write_quality_report(
            processed_records,
            report_path,
            summary_path,
            pages_fetched=len(self.fetched_results),
            failed_urls=self.failed_urls,
        )
        return {
            "extracted_path": str(extracted_path),
            "clean_path": str(clean_path),
            "post_processed_path": str(post_path),
            "final_processed_path": str(final_processed_path),
            "report_path": str(report_path),
            "summary_path": str(summary_path),
            "summary": summary,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape WE Mobile pages with Scrapling.")
    parser.add_argument("--languages", nargs="+", choices=["en", "ar"], default=["en", "ar"])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/scrape_mobile_scrapling_v1"),
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--cache", type=parse_bool, default=True)
    parser.add_argument("--resume", type=parse_bool, default=True)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--force", type=parse_bool, default=False)
    parser.add_argument("--dynamic", type=parse_bool, default=False)
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    spider = MobileScraplingSpider(
        output_dir=args.output_dir,
        languages=args.languages,
        concurrency=args.concurrency,
        delay=args.delay,
        cache=args.cache,
        resume=args.resume,
        max_pages=args.max_pages,
        force=args.force,
        dynamic=args.dynamic,
    )
    return await spider.run()


def main(argv: list[str] | None = None) -> None:
    result = asyncio.run(async_main(argv))
    summary = result["summary"]
    print("WE Mobile Scrapling scrape complete")
    print(f"Total records: {summary['total_records']}")
    print(f"Accepted records: {summary['accepted_records']}")
    print(f"Rejected records: {summary['rejected_records']}")
    print(f"Pages fetched: {summary['number_of_pages_fetched']}")
    print(f"Failed URLs: {len(summary['failed_urls'])}")
    print(f"Processed JSONL: {result['final_processed_path']}")
    print(f"Quality CSV: {result['report_path']}")
    print(f"Summary JSON: {result['summary_path']}")


if __name__ == "__main__":
    main(sys.argv[1:])
