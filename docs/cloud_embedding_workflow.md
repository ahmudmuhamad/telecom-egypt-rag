# Local Scrape, Lightning Embeddings, Docker Restore

This workflow keeps scraping and quality review local, then uses Lightning AI or another cloud
workspace to build embeddings and the Qdrant dense index.

## 1. Scrape and review locally

Scrape the remaining public WE / Telecom Egypt pages:

```powershell
uv run python scripts/scrape_we_public_site.py --max-pages 500 --concurrency 3 --delay 0.75 --cache true --resume true
```

The crawler only follows public `te.eg` pages and skips login, account, checkout, payment, API,
asset, and private-looking URLs.

Outputs:

```text
data/scrape_public_site_v1/01_raw_html/public_site/
data/scrape_public_site_v1/03_clean_records_by_category/public_site/public_site_post_processed.jsonl
data/scrape_public_site_v1/04_quality_reports/public_site/public_site_quality_report.csv
data/processed/public_site/public_site_post_processed.jsonl
```

Review processed sources:

```powershell
uv run python scripts/qa_processed_sources.py --include-disabled
```

Review:

```text
data/quality/processed_sources_qa_report.csv
data/quality/processed_sources_qa_summary.json
```

After review, enable approved sources in `config/kb_sources.yaml`, including:

```yaml
- category: mobile
  path: data/processed/mobile/mobile_post_processed_cleaned.jsonl
  enabled: true

- category: public_site
  path: data/processed/public_site/public_site_post_processed.jsonl
  enabled: true
```

## 2. Package upload bundle for Lightning

```powershell
uv run python scripts/package_lightning_upload.py
```

Upload this file to Lightning:

```text
data/artifacts/lightning_upload_bundle.zip
```

The bundle includes repo code, `config/kb_sources.yaml`, `data/processed/**`, and scrape quality
reports. It intentionally excludes local Qdrant volumes, local uploads, logs, KB build outputs, and
existing indexes.

## 3. Build embeddings and indexes on Lightning

In Lightning, unzip the bundle, install dependencies, start Qdrant, and pull the embedding model:

```bash
unzip lightning_upload_bundle.zip -d telecom-egypt-rag
cd telecom-egypt-rag
uv sync
docker run -d --name telecom_qdrant -p 6333:6333 -p 6334:6334 \
  -v qdrant_storage:/qdrant/storage qdrant/qdrant:v1.14.0
ollama pull qwen3-embedding:4b
```

Set environment values if needed:

```bash
export QDRANT_URL=http://localhost:6333
export OLLAMA_BASE_URL=http://localhost:11434
export QDRANT_COLLECTION=telecom_all_sources_v1
```

Build and export:

```bash
uv run python scripts/cloud_build_artifacts.py --batch-size 16
```

This runs:

```text
scripts/build_unified_kb.py
scripts/build_chunks.py
scripts/build_bm25_index.py
scripts/build_qdrant_index.py --recreate true
scripts/test_retrieval.py "هو ايه الDEX Cordless D1005 دا ؟"
scripts/test_retrieval.py "كود معرفة الرصيد كام؟"
```

Download:

```text
data/artifacts/cloud_index_bundle.zip
```

The bundle contains the Qdrant collection snapshot, `data/knowledge_base`, `data/indexes`, reports,
and `cloud_artifact_manifest.json` with checksums, Qdrant version, embedding model, vector size, and
chunk count.

## 4. Restore locally into Docker

Keep local and cloud Qdrant on the same image tag. Docker Compose uses:

```env
QDRANT_IMAGE=qdrant/qdrant:v1.14.0
```

Start Qdrant:

```powershell
docker compose -f docker/docker-compose.yml up -d qdrant
```

Restore the downloaded artifact:

```powershell
uv run python scripts/restore_cloud_artifacts.py data/artifacts/cloud_index_bundle.zip --qdrant-url http://localhost:6333
```

Then restart the app stack:

```powershell
docker compose -f docker/docker-compose.yml restart streamlit-app
```

## 5. Smoke tests

Run:

```powershell
uv run python scripts/test_retrieval.py "هو ايه الDEX Cordless D1005 دا ؟"
uv run python scripts/test_retrieval.py "كود معرفة الرصيد كام؟"
uv run python scripts/test_retrieval.py "باقة موبايل إنترنت"
```

Expected:

- DEX query ranks `DEX Cordless D1005` first.
- Balance query returns `*550#` and `5 قروش`.
- Mobile/new public-site queries retrieve records from the newly enabled sources.
- Uploaded document ingestion still works locally because uploads upsert into the restored collection.
