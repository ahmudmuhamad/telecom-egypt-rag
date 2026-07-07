# WE Business Scraping With Scrapling

This scraper collects the Telecom Egypt / WE Business section for later manual review and RAG indexing. It is scraping-only: it does not rebuild indexes, modify retrieval, or change the Streamlit app.

## Why Scrapling

Scrapling gives us a respectful static HTTP fetcher with a familiar parser flow, caching/replay support through saved raw HTML, and an optional dynamic fetch path when explicitly requested. The default scraper does not use proxy rotation, stealth bypass, or aggressive anti-bot behavior.

## Coverage

Portal:

```text
https://te.eg/web/te-business
```

Covered categories:

- Mobile Services
- Data Connectivity
- Voice Services
- Hosting / Data Center
- Digital Solutions
- Wholesale

The URL plan is hardcoded in `src/scraping/business_parser.py` so the attached map is treated as a source plan, not strict JSON.

## Outputs

The scraper writes:

```text
data/scrape_business_scrapling_v1/01_raw_html/business/listing_pages/
data/scrape_business_scrapling_v1/01_raw_html/business/detail_pages/
data/scrape_business_scrapling_v1/02_extracted_records/business/business.jsonl
data/scrape_business_scrapling_v1/03_clean_records_by_category/business/business.jsonl
data/scrape_business_scrapling_v1/03_clean_records_by_category/business/business_post_processed.jsonl
data/scrape_business_scrapling_v1/04_quality_reports/business/business_quality_report.csv
data/scrape_business_scrapling_v1/04_quality_reports/business/business_summary.json
data/processed/business/business_post_processed.jsonl
```

## Limited Test

```bash
uv run python scripts/scrape_we_business_scrapling.py --max-pages 5 --concurrency 2 --delay 1.0 --cache true --resume true
```

## Full Scrape

```bash
uv run python scripts/scrape_we_business_scrapling.py --concurrency 3 --delay 1.0 --cache true --resume true
```

Use `--dynamic true` only if static HTML does not contain useful content.

## Review

Open:

```text
data/scrape_business_scrapling_v1/04_quality_reports/business/business_quality_report.csv
data/scrape_business_scrapling_v1/04_quality_reports/business/business_summary.json
```

Check accepted counts, rejected records, quality flags, citation URLs, and whether content is clean enough for RAG. The post-processed JSONL is disabled by default in `config/kb_sources.yaml`.

## Enable After Review

After manual review, set the business source to `enabled: true` in:

```text
config/kb_sources.yaml
```

Then rebuild local artifacts:

```bash
uv run python scripts/build_unified_kb.py
uv run python scripts/build_chunks.py
uv run python scripts/build_bm25_index.py
```

Cloud indexing can happen later with the same embedding model:

```bash
uv run python scripts/build_qdrant_index.py --recreate true --batch-size 1
```

