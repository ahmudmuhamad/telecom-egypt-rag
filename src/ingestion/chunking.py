from __future__ import annotations

import hashlib
import re
from typing import Any


ATOMIC_RECORD_TYPES = {
    "faq",
    "product",
    "service_code",
    "service_fee",
    "package",
    "package_tier",
    "package_price",
    "yearly_package",
    "add_on",
    "payment_channels",
    "salefny_rule",
    "renewal_rule",
    "early_renewal_rule",
    "hardware",
    "table_row",
}

INDEX_METADATA_FIELDS = (
    "service_name",
    "product_name",
    "package_name",
    "brand",
    "product_family",
    "tier",
    "quota",
    "quota_gb",
    "quota_tb",
    "speed",
    "download_speed",
    "upload_speed",
    "subscription_code",
    "ussd_codes",
    "price",
    "price_numeric",
    "price_egp",
    "monthly_fee",
    "monthly_fee_egp",
    "yearly_fee",
    "yearly_fee_egp",
    "fee",
    "fee_notes",
    "search_aliases",
)

TOKEN_PATTERN = re.compile(r"[\w\u0600-\u06FF]+|[*#][\w*#]+|[\w*]+#")


def count_tokens_approx(text: str) -> int:
    return len(TOKEN_PATTERN.findall(text or ""))


def is_atomic_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type") or "").lower()
    category = str(record.get("category") or "").lower()
    token_count = count_tokens_approx(record.get("content") or "")
    if token_count <= int(record.get("_chunk_size", 512)):
        return True
    if record_type in ATOMIC_RECORD_TYPES:
        return True
    if category == "faq":
        return True
    if record_type in {"product", "package", "yearly_package", "add_on"}:
        return True
    return False


def split_text_recursive(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if count_tokens_approx(text) <= chunk_size:
        return [text]

    chunks = _split_by_separators(text, chunk_size, ("\n\n", "\n", ". ", "؟ ", "? ", "! ", " "))
    if not chunks:
        chunks = _split_by_tokens(text, chunk_size)
    return _add_overlap(chunks, chunk_size, chunk_overlap)


def _split_by_separators(text: str, chunk_size: int, separators: tuple[str, ...]) -> list[str]:
    if not separators:
        return _split_by_tokens(text, chunk_size)

    separator = separators[0]
    pieces = text.split(separator)
    if len(pieces) == 1:
        return _split_by_separators(text, chunk_size, separators[1:])

    chunks: list[str] = []
    current: list[str] = []
    for piece in pieces:
        candidate = separator.join([*current, piece]).strip() if current else piece.strip()
        if count_tokens_approx(candidate) <= chunk_size:
            current.append(piece)
            continue
        if current:
            chunks.append(separator.join(current).strip())
            current = []
        if count_tokens_approx(piece) > chunk_size:
            chunks.extend(_split_by_separators(piece, chunk_size, separators[1:]))
        elif piece.strip():
            current = [piece]
    if current:
        chunks.append(separator.join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _split_by_tokens(text: str, chunk_size: int) -> list[str]:
    words = text.split()
    if not words:
        return [text[i : i + chunk_size * 4] for i in range(0, len(text), chunk_size * 4)]
    return [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]


def _add_overlap(chunks: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_overlap <= 0 or len(chunks) <= 1:
        return chunks

    overlapped: list[str] = []
    previous_tokens: list[str] = []
    for chunk in chunks:
        current_tokens = chunk.split()
        prefix = previous_tokens[-chunk_overlap:] if previous_tokens else []
        combined = " ".join([*prefix, *current_tokens]).strip()
        if count_tokens_approx(combined) > chunk_size + chunk_overlap:
            combined = " ".join(combined.split()[-(chunk_size + chunk_overlap) :])
        overlapped.append(combined)
        previous_tokens = current_tokens
    return overlapped


def stable_chunk_id(parent_record_id: str, chunk_index: int, content: str) -> str:
    digest = hashlib.sha256(f"{parent_record_id}:{chunk_index}:{content}".encode("utf-8")).hexdigest()[:16]
    return f"{parent_record_id}:chunk:{chunk_index}:{digest}"


def value_to_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = value_to_text(item)
            if text:
                parts.append(f"{key}: {text}")
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := value_to_text(item)))
    return " ".join(str(value).split())


def build_chunk_index_text(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") or {}
    parts = [
        f"Title: {chunk.get('title', '')}",
        f"Category: {chunk.get('category', '')}",
        f"Record type: {chunk.get('record_type', '')}",
    ]
    if chunk.get("language"):
        parts.append(f"Language: {chunk['language']}")
    for field in INDEX_METADATA_FIELDS:
        text = value_to_text(metadata.get(field))
        if text:
            parts.append(f"{field}: {text}")
    parts.append(f"Content:\n{chunk.get('content', '')}")
    return "\n".join(part for part in parts if part).strip()


def detect_language(text: str) -> str | None:
    has_arabic = bool(re.search(r"[\u0600-\u06FF]", text or ""))
    has_latin = bool(re.search(r"[A-Za-z]", text or ""))
    if has_arabic and has_latin:
        return "mixed"
    if has_arabic:
        return "ar"
    if has_latin:
        return "en"
    return None


def chunk_uploaded_document(
    converted_doc: dict[str, Any],
    upload_session_id: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    document_id = converted_doc["document_id"]
    file_name = converted_doc["file_name"]
    file_type = converted_doc["file_type"]
    title = converted_doc.get("title") or file_name
    sources = _upload_text_sources(converted_doc)

    chunk_parts: list[dict[str, Any]] = []
    for source in sources:
        text = source["text"]
        page_number = source.get("page_number")
        parts = split_text_recursive(text, chunk_size, chunk_overlap) or [text]
        for part in parts:
            if part.strip():
                chunk_parts.append({"content": part.strip(), "page_number": page_number})

    chunks: list[dict[str, Any]] = []
    total_chunks = len(chunk_parts)
    for index, part in enumerate(chunk_parts):
        page_number = part.get("page_number")
        parent_record_id = f"{document_id}:page:{page_number}" if page_number else document_id
        citation_label = _upload_citation_label(file_name, page_number)
        metadata = {
            "file_name": file_name,
            "file_type": file_type,
            "page_number": page_number,
            "document_id": document_id,
            "upload_session_id": upload_session_id,
        }
        content = part["content"]
        chunk = {
            "chunk_id": stable_chunk_id(parent_record_id, index, content),
            "parent_record_id": parent_record_id,
            "document_id": document_id,
            "upload_session_id": upload_session_id,
            "source_type": "user_upload",
            "source_name": "Uploaded Document",
            "category": "uploaded_document",
            "record_type": "uploaded_chunk",
            "language": detect_language(content),
            "title": title,
            "content": content,
            "index_text": "",
            "citation_url": None,
            "citation_label": citation_label,
            "file_name": file_name,
            "file_type": file_type,
            "page_number": page_number,
            "chunk_index": index,
            "total_chunks": total_chunks,
            "metadata": metadata,
        }
        chunk["index_text"] = build_upload_chunk_index_text(chunk)
        chunks.append(chunk)
    return chunks


def build_upload_chunk_index_text(chunk: dict[str, Any]) -> str:
    page_number = chunk.get("page_number")
    parts = [
        f"Title: {chunk.get('title') or ''}",
        f"File name: {chunk.get('file_name') or ''}",
        f"File type: {chunk.get('file_type') or ''}",
        f"Page: {page_number}" if page_number else "",
        f"Content:\n{chunk.get('content') or ''}",
    ]
    return "\n".join(part for part in parts if part).strip()


def _upload_text_sources(converted_doc: dict[str, Any]) -> list[dict[str, Any]]:
    pages = converted_doc.get("pages") or []
    page_sources: list[dict[str, Any]] = []
    for page in pages:
        text = (page.get("text") or page.get("markdown") or "").strip()
        if text:
            page_sources.append({"text": text, "page_number": page.get("page_number")})
    if page_sources:
        return page_sources
    text = (converted_doc.get("text") or converted_doc.get("markdown") or "").strip()
    return [{"text": text, "page_number": None}] if text else []


def _upload_citation_label(file_name: str, page_number: Any) -> str:
    if page_number:
        return f"Uploaded document — {file_name}, page {page_number}"
    return f"Uploaded document — {file_name}"


def chunk_record(record: dict[str, Any], chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    working_record = {**record, "_chunk_size": chunk_size}
    atomic = is_atomic_record(working_record)
    content_parts = [record["content"]] if atomic else split_text_recursive(
        record.get("content") or "",
        chunk_size,
        chunk_overlap,
    )
    if not content_parts:
        content_parts = [record.get("content") or ""]

    chunks: list[dict[str, Any]] = []
    total_chunks = len(content_parts)
    for index, content in enumerate(content_parts):
        chunk = {
            "chunk_id": stable_chunk_id(record["record_id"], index, content),
            "parent_record_id": record["record_id"],
            "kb_version": record.get("kb_version"),
            "source_type": record.get("source_type", "official_website"),
            "source_name": record.get("source_name", "Telecom Egypt"),
            "category": record.get("category"),
            "record_type": record.get("record_type"),
            "language": record.get("language"),
            "title": record.get("title"),
            "content": content,
            "index_text": "",
            "citation_url": record.get("citation_url"),
            "chunk_index": index,
            "total_chunks": total_chunks,
            "metadata": record.get("metadata") or {},
        }
        chunk["index_text"] = build_chunk_index_text(chunk)
        chunks.append(chunk)
    return chunks
