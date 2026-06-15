# WE Mobile Scrapling Scraper

This proof of concept scrapes the official WE Mobile pages in English and Arabic and prepares
RAG-friendly JSONL records for manual review before indexing. It does not rebuild indexes or
change the running Streamlit/RAG pipeline.

## Why Scrapling

Scrapling is used for respectful website fetching with browser-style HTTP requests, async
concurrency, selector-friendly HTML parsing, and optional dynamic fetching. The scraper defaults to
normal static fetching, low concurrency, a delay between requests, robots.txt checks where
available, raw HTML caching, and checkpoint-based resume.

Dynamic fetching is off by default. Do not use stealth, proxy rotation, or anti-bot bypass features
unless static fetching fails and the reason is documented.

## Install

```powershell
uv add "scrapling[fetchers]"
```

If the fetcher extra is too heavy for a local environment, install plain Scrapling and keep dynamic
fetching disabled:

```powershell
uv add scrapling
```

## Run

Limited English smoke test:

```powershell
uv run python scripts/scrape_we_mobile_scrapling.py --languages en --max-pages 5 --concurrency 2 --delay 1.0 --cache true --resume true
```

Full English and Arabic scrape:

```powershell
uv run python scripts/scrape_we_mobile_scrapling.py --languages en ar --concurrency 3 --delay 1.0 --cache true --resume true
```

Use `--dynamic true` only when static HTML is too thin for a specific page.

## Cleanup Before Indexing

Run the cleanup pass after scraping and before enabling the mobile source. It removes UI/navigation
noise from `content`, rebuilds answer-friendly content, extracts full USSD/subscription codes,
handles Super Kix units and usage rules, and writes `index_text` for retrieval.

```powershell
uv run python scripts/clean_mobile_post_processed.py
```

Outputs:

```text
data/processed/mobile/mobile_post_processed_cleaned.jsonl
data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/mobile_cleanup_report.csv
data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/mobile_cleanup_summary.json
```

If you intentionally rerun the cleanup and want to replace the cleaned file:

```powershell
uv run python scripts/clean_mobile_post_processed.py --overwrite true
```

## Outputs

Raw HTML:

```text
data/scrape_mobile_scrapling_v1/01_raw_html/mobile/{en,ar}/{listing_pages,detail_pages}/
```

Extracted and post-processed records:

```text
data/scrape_mobile_scrapling_v1/02_extracted_records/mobile/mobile.jsonl
data/scrape_mobile_scrapling_v1/03_clean_records_by_category/mobile/mobile.jsonl
data/scrape_mobile_scrapling_v1/03_clean_records_by_category/mobile/mobile_post_processed.jsonl
data/processed/mobile/mobile_post_processed.jsonl
data/processed/mobile/mobile_post_processed_cleaned.jsonl
```

Quality review:

```text
data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/mobile_quality_report.csv
data/scrape_mobile_scrapling_v1/04_quality_reports/mobile/mobile_summary.json
```

Review `mobile_quality_report.csv` and `mobile_cleanup_report.csv` for rejected rows, missing
citations, language mismatches, remaining UI noise, suspicious partial codes, and Kix quota
corrections before enabling indexing.

## Enable for KB Build

`config/kb_sources.yaml` points to `mobile_post_processed_cleaned.jsonl` with `enabled: false` by
default. After reviewing the cleaned file and cleanup report, set it to `true`, then rebuild the KB
and indexes manually:

```powershell
uv run python scripts/build_unified_kb.py
uv run python scripts/build_chunks.py
uv run python scripts/build_bm25_index.py
uv run python scripts/build_qdrant_index.py --recreate true --batch-size 1
```
