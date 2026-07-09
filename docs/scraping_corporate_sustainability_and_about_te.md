# Scraping Corporate Sustainability And About TE

This scraper adds two official Telecom Egypt sections for review before they are included in the RAG knowledge base:

- `corporate_sustainability`
- `about_te`

It only scrapes, extracts, post-processes, writes quality reports, and writes disabled KB source entries. It does not rebuild dense vectors, Qdrant indexes, retrieval logic, generation logic, or the Streamlit UI.

## Covered URLs

Corporate Sustainability:

```text
https://te.eg/en/Corporate-Sustainability/
https://te.eg/en/web/guest/corporate-sustainability/sustainability
https://te.eg/en/web/guest/corporate-sustainability/climate-change
https://te.eg/en/web/guest/corporate-sustainability/corporate-quality
https://te.eg/Corporate-Sustainability/
https://te.eg/Corporate-Sustainability/Sustainability
https://te.eg/Corporate-Sustainability/climate-change
https://te.eg/Corporate-Sustainability/corporate-quality
```

About TE:

```text
https://te.eg/en/about-te/
https://te.eg/en/about-te/board-of-directors
https://te.eg/en/about-te/management-team
https://te.eg/en/about-te/te-museum
https://te.eg/en/about-te/history
https://te.eg/en/about-te/awards
https://te.eg/en/about-te/corporate-strategy
https://te.eg/en/about-te/press-releases
https://te.eg/en/about-te/tv-ads
https://te.eg/en/about-te/careers-and-training
https://te.eg/en/about-te/contact-us
https://te.eg/about-te/
https://te.eg/about-te/board-of-directors
https://te.eg/about-te/management-team
https://te.eg/about-te/te-museum
https://te.eg/about-te/history
https://te.eg/about-te/awards
https://te.eg/about-te/corporate-strategy
https://te.eg/about-te/press-releases
https://te.eg/about-te/tv-ads
https://te.eg/about-te/careers-and-training
https://te.eg/about-te/contact-us
```

## Output Folders

Corporate Sustainability:

```text
data/scrape_corporate_sustainability_scrapling_v1/
  01_raw_html/corporate_sustainability/
  02_extracted_records/corporate_sustainability/corporate_sustainability.jsonl
  03_clean_records_by_category/corporate_sustainability/
  04_quality_reports/corporate_sustainability/
data/processed/corporate_sustainability/corporate_sustainability_post_processed.jsonl
```

About TE:

```text
data/scrape_about_te_scrapling_v1/
  01_raw_html/about_te/
  02_extracted_records/about_te/about_te.jsonl
  03_clean_records_by_category/about_te/
  04_quality_reports/about_te/
data/processed/about_te/about_te_post_processed.jsonl
```

## Limited Test

Run both sections together:

```bash
uv run python scripts/scrape_section_scrapling.py corporate_sustainability about_te --max-pages 10 --concurrency 2 --delay 1.0 --cache true --resume true
```

Review:

```text
data/scrape_corporate_sustainability_scrapling_v1/04_quality_reports/corporate_sustainability/corporate_sustainability_quality_report.csv
data/scrape_corporate_sustainability_scrapling_v1/04_quality_reports/corporate_sustainability/corporate_sustainability_summary.json
data/scrape_about_te_scrapling_v1/04_quality_reports/about_te/about_te_quality_report.csv
data/scrape_about_te_scrapling_v1/04_quality_reports/about_te/about_te_summary.json
```

The limited test should produce raw HTML, extracted JSONL, post-processed JSONL, and accepted records for each section.

## Full Scrape

After the limited test looks good:

```bash
uv run python scripts/scrape_section_scrapling.py corporate_sustainability about_te --concurrency 2 --delay 1.0 --cache true --resume true
```

The scraper uses static Scrapling fetching, low concurrency, delay, cache, resume, raw HTML saving, and failure logging. It does not use proxies, stealth, or dynamic browser fetching by default.

## Colab Run

In the Colab notebook configuration cell, set:

```python
ENABLED_SECTIONS = ["corporate_sustainability", "about_te"]
MAX_PAGES_PER_SECTION = 10
CONCURRENCY = 2
DELAY_SECONDS = 1.0
```

Then run the setup, dependency, prepare runner, and scrape sections cells. If you are only reviewing these scraped sources, stop after the quality reports. Dense embeddings and Qdrant indexing can be done later.

## Enable After Review

Both sources are added to `config/kb_sources.yaml` with:

```yaml
enabled: false
```

After manually reviewing quality reports and processed records, change the desired sources to:

```yaml
enabled: true
```

Then rebuild the official KB artifacts:

```bash
uv run python scripts/build_unified_kb.py
uv run python scripts/build_chunks.py
uv run python scripts/build_bm25_index.py
```

Dense embeddings and Qdrant indexing should be run only after review, using the same embedding model as the local app.

## Validation

Run:

```bash
uv run python -m compileall src/scraping scripts/scrape_section_scrapling.py
uv run ruff check src/scraping scripts/scrape_section_scrapling.py
```

Then verify:

- Raw HTML files exist.
- Extracted JSONL files exist.
- Post-processed JSONL files exist.
- Quality CSV files exist.
- Summary JSON files exist.
- `accepted_records > 0` for each section.
