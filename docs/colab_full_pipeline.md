# Telecom Egypt RAG Colab Full Pipeline

This guide explains how to build Telecom Egypt RAG data and indexes in Google Colab, then restore the finished Qdrant snapshot locally. Colab is used only as a temporary build machine for scraping, processing, embedding, and snapshot creation. The local Streamlit app, retrieval logic, and generation logic are not changed by this pipeline.

## Files

- Notebook: `notebooks/telecom_rag_colab_full_pipeline.ipynb`
- Script runner: `scripts/colab_full_pipeline.py`
- Drive workspace: `/content/drive/MyDrive/telecom_egypt_rag_colab/`

## What It Does

The pipeline can:

- Mount Google Drive and create persistent output folders.
- Clone or update the project in Colab.
- Run section-limited Scrapling scraping with cache/resume.
- Save raw HTML, extracted JSONL, processed JSONL, and quality reports.
- Build the unified official KB, chunks, and BM25 index with the existing project scripts.
- Install and run Ollama.
- Pull and use `qwen3-embedding:4b` through Ollama `/api/embed`.
- Start Qdrant with `udocker` in Colab, or Docker where a Docker daemon is available, with Drive-backed storage and snapshots.
- Create `telecom_all_sources_v2` using detected vector size and cosine distance.
- Embed chunks, upsert them to Qdrant, and write a resumable progress file.
- Export both a Qdrant snapshot and `embedded_points_v2.jsonl.gz`.
- Write final JSON and Markdown reports.

## Drive Output Layout

All important artifacts are saved under:

```text
/content/drive/MyDrive/telecom_egypt_rag_colab/
  raw_html/
  extracted_records/
  processed/
  knowledge_base/
  chunks/
  bm25/
  qdrant_storage/
  qdrant_snapshots/
  embedded_points/
  quality_reports/
  logs/
  manifests/
```

Do not rely on `/content` for final artifacts. Colab runtimes are temporary.

## How To Run

1. Open `notebooks/telecom_rag_colab_full_pipeline.ipynb` in Google Colab.
2. Set `REPO_URL` in the clone cell if the repo is not already present.
3. Run the Drive mount, configuration, clone, dependency, and runner setup cells.
4. Keep the default limited test mode first:

```python
MAX_PAGES_PER_SECTION = 5
CONCURRENCY = 2
DELAY_SECONDS = 1.0
RUN_FULL_MODE = False
```

5. Run `Scrape Sections` and inspect:

```text
raw_html/
extracted_records/
processed/
quality_reports/
```

6. If outputs look good, set:

```python
RUN_FULL_MODE = True
CONCURRENCY = 3
DELAY_SECONDS = 1.0
```

7. Rerun the stages from scraping onward, or continue with build/index stages if the scrape is complete.

## Configure Sections

Section settings live in `default_sections()` inside `scripts/colab_full_pipeline.py`. Each section supports:

- `name`
- `enabled`
- `seeds`
- `allow_patterns`
- `deny_patterns`
- `output_folder`
- `parser`
- `customer_segment`

Only `business` is enabled by default. `mobile` can be enabled from the notebook with:

```python
ENABLE_MOBILE = True
```

Other sections (`landline`, `support`, `about`, `personal`, `devices`, `services`, `we_home`) are present as disabled placeholders so new seed URLs and URL filters can be added later without changing the pipeline shape.

## Resume Behavior

The scraper writes checkpoints to:

```text
manifests/<section>_scrape_checkpoint.json
```

Embedding progress is saved to:

```text
manifests/embedded_completed_chunk_ids.txt
```

Failures are appended to:

```text
logs/embedding_failures.jsonl
```

Reruns skip cached fetched pages and completed chunk IDs by default. To force reruns:

```python
FORCE_REFETCH = True
FORCE_REEMBED = True
```

Processed files are copied to `data/processed/<section>/`. Existing processed files are not overwritten unless:

```python
OVERWRITE_PROCESSED = True
```

When overwrite is false and a target exists, the pipeline writes a timestamped file.

## Build Outputs

The KB/chunk/BM25 stages call the existing scripts:

```bash
python scripts/build_unified_kb.py
python scripts/build_chunks.py
python scripts/build_bm25_index.py
```

If `uv` is available, the runner uses:

```bash
uv run python ...
```

The pipeline also writes a Colab-specific source config:

```text
config/kb_sources_colab.yaml
manifests/kb_sources_colab.yaml
```

## Qdrant and Embeddings

The notebook installs Ollama and pulls exactly:

```text
qwen3-embedding:4b
```

The Ollama stage installs Colab system helpers before pulling the model:

```bash
sudo apt update
sudo apt install -y pciutils zstd
```

`zstd` is required for extracting current Ollama model layers in Colab. The notebook starts `ollama serve` in a background Python thread, waits for `http://localhost:11434/api/tags`, then runs:

```bash
ollama pull qwen3-embedding:4b
```

Embeddings are generated with:

```text
http://localhost:11434/api/embed
```

The first embedding is used to detect vector size. The expected size is likely `2560`, but the pipeline does not hardcode it.

Qdrant runs as a real server on `localhost:6333`, not embedded local mode.

The Colab notebook defaults to `udocker` because Colab often blocks the standard Docker daemon:

```python
QDRANT_RUNTIME = "udocker"
QDRANT_IMAGE = "qdrant/qdrant:v1.14.0"
```

The runner installs and initializes `udocker` with `--allow-root`, pulls the Qdrant image, creates a `qdrant_colab` container, mounts Drive-backed Qdrant folders, and waits for the HTTP API.

Equivalent manual `udocker` commands:

```bash
pip install udocker
udocker --allow-root install
udocker --allow-root pull qdrant/qdrant:v1.14.0
udocker --allow-root rm qdrant_colab || true
udocker --allow-root create --name=qdrant_colab qdrant/qdrant:v1.14.0
udocker --allow-root run \
  -v /content/drive/MyDrive/telecom_egypt_rag_colab/qdrant_storage:/qdrant/storage \
  -v /content/drive/MyDrive/telecom_egypt_rag_colab/qdrant_snapshots:/qdrant/snapshots \
  qdrant_colab
```

If you are running somewhere with a working Docker daemon, set:

```python
QDRANT_RUNTIME = "docker"
```

Docker equivalent:

```bash
docker run -d \
  --name qdrant_colab \
  -p 6333:6333 \
  -v /content/drive/MyDrive/telecom_egypt_rag_colab/qdrant_storage:/qdrant/storage \
  -v /content/drive/MyDrive/telecom_egypt_rag_colab/qdrant_snapshots:/qdrant/snapshots \
  qdrant/qdrant:v1.14.0
```

Default collection:

```text
telecom_all_sources_v2
```

Distance metric:

```text
cosine
```

## Restore Qdrant Snapshot Locally

1. Download the snapshot file from Drive or the notebook download cell.
2. Make sure local Docker Qdrant is running on port `6333`.
3. Upload the snapshot with Windows PowerShell:

```powershell
curl.exe -X POST "http://localhost:6333/collections/telecom_all_sources_v2/snapshots/upload?priority=snapshot" `
     -H "Content-Type: multipart/form-data" `
     -F "snapshot=@C:\Users\<YOUR_USER>\Downloads\<SNAPSHOT_FILE>.snapshot"
```

4. Set the local `.env` collection name:

```env
QDRANT_COLLECTION_NAME=telecom_all_sources_v2
```

5. Restart the local app:

```bash
uv run streamlit run app/streamlit_app.py
```

## Validate Local Retrieval

Run:

```bash
uv run python scripts/test_retrieval.py "Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)"
uv run python scripts/test_retrieval.py "Tell me about WE Business Value 175"
```

Expected results:

- No vector dimension mismatch.
- Correct source section/category is returned.
- Source URLs are preserved.
- Retrieval-only Streamlit mode shows useful source cards.

## Common Colab Issues

- **Runtime disconnects:** rerun from the last completed stage. Drive checkpoints and embedding progress should allow resume.
- **Ollama model pull says zstd is required:** rerun the Ollama cell. It installs `zstd` before `ollama pull`.
- **Ollama out of memory:** keep `EMBED_BATCH_SIZE = 1` and use a GPU runtime when available.
- **Docker not available:** use the default `QDRANT_RUNTIME = "udocker"` in Colab. Qdrant snapshots still use server mode on `localhost:6333`.
- **Slow scraping:** keep concurrency low. The default is respectful and section-limited.
- **No snapshot file found:** check `manifests/qdrant_snapshot_manifest.json` and search both `qdrant_snapshots/` and `qdrant_storage/`.
- **Existing processed file not updated:** set `OVERWRITE_PROCESSED = True` only when you intentionally want to replace the target.

## Local Validation For This Implementation

Run locally after code changes:

```bash
uv run python -m compileall scripts/colab_full_pipeline.py
uv run ruff check scripts/colab_full_pipeline.py
```

Do not run the full Colab pipeline locally unless you intentionally want network scraping, Ollama embedding, a Qdrant server, and large artifact creation.
