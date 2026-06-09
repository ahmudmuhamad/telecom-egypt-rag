from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBSourceFileConfig(BaseModel):
    category: str
    path: Path
    enabled: bool = True
    description: str | None = None


class UnifiedKBRecord(BaseModel):
    record_id: str
    kb_version: str
    source_type: str = "official_website"
    source_name: str = "Telecom Egypt"
    category: str
    record_type: str
    language: str | None = None
    title: str
    content: str
    index_text: str
    citation_url: str
    quality_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_source_file: str


class KBRejectedRecord(BaseModel):
    source_file: str
    category: str | None = None
    raw_record_id: str | None = None
    title: str | None = None
    rejection_reason: str
    raw_record: dict[str, Any] = Field(default_factory=dict)


class KBManifest(BaseModel):
    kb_version: str
    created_at: str
    embedding_provider: str
    embedding_model: str
    index_version: str
    source_files: list[dict[str, Any]]
    total_input_records: int
    total_accepted_records: int
    total_rejected_records: int
    accepted_by_category: dict[str, int]
    accepted_by_language: dict[str, int]
    accepted_by_record_type: dict[str, int]
