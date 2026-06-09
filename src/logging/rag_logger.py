from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, settings

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None


class RAGLogger:
    def __init__(self, log_dir: Path | None = None) -> None:
        self.log_dir = self._resolve_path(log_dir or settings.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    def _write_jsonl(self, filename: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        path = self.log_dir / filename
        if orjson is not None:
            line = orjson.dumps(event).decode("utf-8")
        else:
            line = json.dumps(event, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._write_jsonl("rag_events.jsonl", event_type, payload)

    def log_query(self, payload: dict[str, Any]) -> None:
        self._write_jsonl("rag_queries.jsonl", "query", payload)

    def log_error(self, error_type: str, payload: dict[str, Any]) -> None:
        self._write_jsonl("rag_errors.jsonl", error_type, payload)
