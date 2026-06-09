# Git Workflow

## Branching Strategy

- `main`: stable, demo-ready branch.
- `develop`: integration branch for completed phases.
- `feature/<short-name>`: new feature work.
- `fix/<short-name>`: bug fixes.
- `experiment/<short-name>`: temporary experiments.
- `docs/<short-name>`: documentation-only changes.

Recommended current branch:

```bash
git checkout -b feature/local-foundation
```

Before running Codex changes, create or switch to a feature branch.

## Commit Strategy

- Commit after each working phase.
- Use small meaningful commits.
- Do not commit broken infrastructure.
- Do not commit `.env`, uploads, indexes, logs, cache files, model files, or local vector DB storage.
- Commit curated processed input JSONL files only if intentionally part of the project.
- Commit `uv.lock` if generated.
- Commit Docker Compose and configuration templates.

Commit message examples:

- `chore: initialize local RAG foundation`
- `chore: add docker compose infrastructure`
- `feat: add Ollama and Qdrant service clients`
- `feat: add Prometheus metrics scaffolding`
- `docs: document local setup and git workflow`

After this task:

```bash
git status
git add .
git commit -m "chore: add local foundation infrastructure"
```

## Pull Request Checklist

- Does `uv sync` work?
- Does Docker Compose start?
- Is `.env` excluded?
- Are generated indexes/logs/uploads excluded?
- Are no large binary/model files committed?
- Is README updated?
- Is the next phase clearly documented?
