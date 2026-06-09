# Telecom Egypt Intelligent Assistant

## Overview

This project is a local on-prem Retrieval-Augmented Generation assistant for Telecom Egypt official website data and, in later phases, uploaded reviewer/customer documents.

The current work moves the project from Colab experimentation toward a reproducible local implementation using uv, Docker Compose, Ollama, Qdrant, Prometheus, and Grafana.

## Current Scope

This foundation stage includes dependency management, environment settings, infrastructure configuration, local service clients, Prometheus metric definitions, JSONL logging, cost optimization scaffolding, model routing scaffolding, and reviewer/developer documentation.

It does not yet implement unified KB building, chunking, indexing, hybrid retrieval, reranking integration, answer generation, upload processing, evaluation, or the Streamlit chat UI flow.

## Architecture

- `app/`: Streamlit application placeholder for later phases.
- `config/`: environment templates and typed settings.
- `data/`: curated inputs, generated indexes, uploads, logs, and knowledge-base artifacts.
- `docker/`: Docker Compose, Prometheus, and future Grafana provisioning.
- `scripts/`: operational scripts for indexing/evaluation phases and model pulls.
- `src/services/`: Ollama, Qdrant, metrics, cache, and logging helpers.
- `src/retrieval/`: retrieval modules plus model routing scaffolding.

## Data Sources

Current curated processed input files:

- FAQ: `data/processed/faq/faq_post_processed.jsonl`
- Devices: `data/processed/devices/devices_post_processed_v2.jsonl`
- Services: `data/processed/services/services_post_processed_v3.jsonl`
- WE Home: `data/processed/we_home/we_home.jsonl`

These JSONL files are project inputs and should remain trackable unless the team intentionally changes that policy.

## Local On-Prem Stack

- Ollama for local embedding and generation models.
- Qdrant for dense vector search.
- BM25 planned later for sparse retrieval.
- Prometheus for metrics collection.
- Grafana for dashboards.
- Rule-based query/model routing first, with LLM routing deferred.

## Dependency Management with uv

Install uv if needed:

```bash
pip install uv
```

Create the virtual environment:

```bash
uv venv
```

Install dependencies:

```bash
uv sync
```

Run Python commands through uv:

```bash
uv run python -m src.retrieval.model_router
```

Dependencies are defined in `pyproject.toml`. `requirements.txt` is only a pointer for uv-based setup.

## Git Workflow and Branching Strategy

Create or switch to a feature branch before each implementation phase:

```bash
git checkout -b feature/local-foundation
```

Recommended branches:

- `main`: stable, demo-ready branch.
- `develop`: integration branch for completed phases.
- `feature/<short-name>`: new feature work.
- `fix/<short-name>`: bug fixes.
- `experiment/<short-name>`: temporary experiments.
- `docs/<short-name>`: documentation-only changes.

Commit after each working phase with small meaningful commits. Never commit `.env`, uploads, logs, generated indexes, Qdrant storage, Ollama storage, Grafana storage, local database files, cache files, model files, or large binary artifacts.

After this task, a human developer can run:

```bash
git status
git add .
git commit -m "chore: add local foundation infrastructure"
```

See `docs/git_workflow.md` for the full workflow and checklist.

## Starting Infrastructure

Start local infrastructure:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Check containers:

```bash
docker ps
```

Check Qdrant:

```bash
curl http://localhost:6333
```

Check Ollama:

```bash
curl http://localhost:11434/api/tags
```

Open services:

- Qdrant: http://localhost:6333/dashboard
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000

The final reviewer flow will eventually be:

```bash
docker compose -f docker/docker-compose.yml up --build
```

During current development, indexing and app startup are still run manually until later phases are completed.

## Ollama Models

Pull models manually after the Ollama container is running:

```bash
docker exec -it telecom_ollama ollama pull qwen3-embedding:4b
docker exec -it telecom_ollama ollama pull qwen3.5:0.8b
docker exec -it telecom_ollama ollama pull qwen3.5:2b
docker exec -it telecom_ollama ollama pull qwen3:4b
```

Linux/macOS/Git Bash users can run:

```bash
scripts/pull_ollama_models.sh
```

Windows PowerShell users can run the `docker exec` commands manually if shell script execution is not available.

## Reviewer Quick Start

1. Clone the repository.
2. Copy `config/.env.example` to `config/.env`.
3. Run `uv venv`.
4. Run `uv sync`.
5. Start infrastructure with `docker compose -f docker/docker-compose.yml up -d`.
6. Pull the Ollama models manually.
7. Run `uv run python -m src.services.ollama_client`.
8. Run `uv run python -m src.retrieval.model_router`.

Expected future final flow:

1. Clone repo.
2. Copy `.env.example` to `.env`.
3. Run Docker Compose.
4. Pull Ollama models.
5. Build unified KB.
6. Build Qdrant index.
7. Build BM25 index.
8. Run Streamlit app.
9. Open http://localhost:8501.

## Developer Setup

Use `config/.env.example` as the source of supported environment variables. The typed settings object is exposed as `settings` from `config.settings`.

Useful checks:

```bash
uv run python -m src.services.ollama_client
uv run python -m src.retrieval.model_router
```

Docker commands should be run manually by the developer. Application code should not pull models or start infrastructure automatically.

## Monitoring with Prometheus and Grafana

Prometheus is configured to scrape:

- Prometheus itself at `localhost:9090`.
- Future RAG API metrics at `host.docker.internal:8000`.
- Qdrant at `qdrant:6333` when metrics are available for the running Qdrant version/configuration.

Grafana is available at http://localhost:3000 with `admin` / `admin`. Prometheus can be added manually as a data source now, with provisioning planned for a later phase.

## Cost Optimization Plan

Cost and latency controls are scaffolded in this order:

- Exact cache
- Semantic cache
- Embedding cache
- Prompt cache
- Context compression
- Model routing
- Model fallback

Only in-memory exact and embedding cache scaffolding exists now. Semantic cache and prompt cache are placeholders for later integration.

## Model Routing Plan

Rule-based routing is implemented first:

- Simple factual Q&A -> `qwen3.5:0.8b`
- Normal RAG answers -> `qwen3.5:2b`
- Complex reasoning/comparison/upload analysis -> `qwen3:4b`

LLM-based routing may be added later after the rule-based baseline is validated.

## Future Data Expansion

More Telecom Egypt website data can be added later through:

- A new processed JSONL category file.
- A new entry in `config/kb_sources.yaml`.
- The unified KB builder.
- Re-indexing or incremental Qdrant upsert.
- BM25 rebuild or incremental update.
- Evaluation regression tests.

## Knowledge Base and Indexing Workflow

Build the unified official KB:

```bash
uv run python scripts/build_unified_kb.py
```

Build chunks:

```bash
uv run python scripts/build_chunks.py
```

Start infrastructure:

```bash
docker compose -f docker/docker-compose.yml up -d
```

Pull the embedding model if needed:

```bash
docker exec -it telecom_ollama ollama pull qwen3-embedding:4b
```

Build the Qdrant dense vector index:

```bash
uv run python scripts/build_qdrant_index.py
```

Build the BM25 keyword index:

```bash
uv run python scripts/build_bm25_index.py
```

Qdrant stores dense vectors generated from chunk `index_text` using `qwen3-embedding:4b`. BM25 stores a keyword index over the same `index_text`. Future retrieval will combine Qdrant and BM25 results with reciprocal rank fusion. `content` remains the display and answer-generation text, while citations come from `citation_url`.

More website data can be added without changing the RAG architecture:

1. Add a processed file such as `data/processed/mobile/mobile_post_processed.jsonl`.
2. Add a YAML source entry:

```yaml
- category: mobile
  path: data/processed/mobile/mobile_post_processed.jsonl
  enabled: true
  description: Mobile bundles, add-ons, and offers
```

3. Rebuild:

```bash
uv run python scripts/build_unified_kb.py
uv run python scripts/build_chunks.py
uv run python scripts/build_qdrant_index.py
uv run python scripts/build_bm25_index.py
```

## Retrieval Testing

Phase 4 implements terminal-testable retrieval only. It does not generate answers, run Streamlit, process uploads, use Docling, use Redis, use semantic cache, or run a reranker model yet.

Dense retrieval uses Qdrant with local Ollama query embeddings from `qwen3-embedding:4b`. BM25 keyword retrieval uses `data/indexes/bm25_official_kb_v1.pkl`. Hybrid retrieval combines dense and BM25 hits with reciprocal rank fusion, then applies small metadata-aware boosts for service codes, prices, WE Home packages, devices, and language hints. Returned rows are ranked chunks with citations.

Run individual retrieval checks:

```bash
uv run python scripts/test_retrieval.py "What is the yearly fee for WE Space Mega 3000 GB?"
uv run python scripts/test_retrieval.py "كود معرفة الرصيد كام؟"
uv run python scripts/test_retrieval.py "ازاي أعرف رصيدي؟"
uv run python scripts/test_retrieval.py "What is the SIM swap cost?"
uv run python scripts/test_retrieval.py "سعر راوتر TP-Link كام؟"
uv run python scripts/test_retrieval.py "What are WE Space recharge add-ons?"
```

Useful options:

```bash
uv run python scripts/test_retrieval.py "What is the SIM swap cost?" --debug
uv run python scripts/test_retrieval.py "What is the SIM swap cost?" --json
uv run python scripts/test_retrieval.py "What is the SIM swap cost?" --show-content
```

Run the retrieval eval:

```bash
uv run python scripts/run_retrieval_eval.py
```

The eval creates `data/evaluation/golden_queries_v1.jsonl` if it does not exist and writes `data/evaluation/retrieval_eval_results_v1.csv`.

Success criteria:

- Correct category appears in the top 5 where a category is expected.
- Expected answer tokens appear in the top 5.
- Citation URL is present and matches expected source hints where provided.
- Out-of-scope queries are rejected by the router.

## Next Implementation Phases

- Reranking integration.
- Answer generation with citations.
- Streamlit chat UI.
- Docling upload processing.
- Evaluation and regression checks.
