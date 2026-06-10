from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


class DoclingConverter:
    text_extensions = {"txt"}
    html_extensions = {"html", "htm"}

    def convert_file(self, file_path: Path, upload_session_id: str = "") -> dict[str, Any]:
        file_path = Path(file_path)
        file_type = self.detect_file_type(file_path)
        document_id = self.safe_document_id(file_path, upload_session_id)

        try:
            if file_type in self.text_extensions:
                return self._convert_text(file_path, document_id, file_type)
            if file_type in self.html_extensions:
                return self._convert_html(file_path, document_id, file_type)
            return self._convert_with_docling(file_path, document_id, file_type)
        except Exception as exc:
            return {
                "document_id": document_id,
                "file_name": file_path.name,
                "file_type": file_type,
                "title": file_path.stem,
                "markdown": "",
                "text": "",
                "pages": [],
                "metadata": {},
                "error": str(exc),
            }

    def safe_document_id(self, file_path: Path, upload_session_id: str) -> str:
        file_path = Path(file_path)
        digest = hashlib.sha256()
        digest.update((upload_session_id or "").encode("utf-8"))
        digest.update(file_path.name.encode("utf-8"))
        with file_path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return f"upload_{digest.hexdigest()[:24]}"

    def detect_file_type(self, file_path: Path) -> str:
        return Path(file_path).suffix.lower().lstrip(".") or "unknown"

    def write_processed_outputs(self, result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        document_id = result["document_id"]
        json_path = output_dir / f"{document_id}.json"
        markdown_path = output_dir / f"{document_id}.md"

        with json_path.open("w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
            file.write("\n")

        markdown = result.get("markdown") or result.get("text") or ""
        if markdown:
            markdown_path.write_text(markdown, encoding="utf-8")

        return {
            "json_path": str(json_path),
            "markdown_path": str(markdown_path) if markdown else None,
        }

    def _convert_text(self, file_path: Path, document_id: str, file_type: str) -> dict[str, Any]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return self._result(file_path, document_id, file_type, text=text, markdown=text, pages=[])

    def _convert_html(self, file_path: Path, document_id: str, file_type: str) -> dict[str, Any]:
        raw_html = file_path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw_html, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else file_path.stem
        text = soup.get_text("\n")
        markdown = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        result = self._result(file_path, document_id, file_type, text=markdown, markdown=markdown, pages=[])
        result["title"] = title
        return result

    def _convert_with_docling(self, file_path: Path, document_id: str, file_type: str) -> dict[str, Any]:
        try:
            from docling.document_converter import DocumentConverter
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Document conversion is unavailable in this environment.") from exc

        converter = DocumentConverter()
        converted = converter.convert(str(file_path))
        document = getattr(converted, "document", converted)
        markdown = self._export_document(document, "export_to_markdown")
        text = self._export_document(document, "export_to_text") or markdown
        pages = self._extract_pages(document)
        title = getattr(document, "name", None) or file_path.stem
        return {
            "document_id": document_id,
            "file_name": file_path.name,
            "file_type": file_type,
            "title": str(title),
            "markdown": markdown,
            "text": text,
            "pages": pages,
            "metadata": {},
        }

    def _export_document(self, document: Any, method_name: str) -> str:
        method = getattr(document, method_name, None)
        if not callable(method):
            return ""
        try:
            return str(method() or "")
        except Exception:
            return ""

    def _extract_pages(self, document: Any) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        raw_pages = getattr(document, "pages", None)
        if not raw_pages:
            return pages
        page_items = raw_pages.values() if isinstance(raw_pages, dict) else raw_pages
        for index, page in enumerate(page_items, start=1):
            page_number = getattr(page, "page_no", None) or getattr(page, "page_number", None) or index
            page_text = self._export_document(page, "export_to_text") or str(getattr(page, "text", "") or "")
            page_markdown = self._export_document(page, "export_to_markdown") or page_text
            if page_text or page_markdown:
                pages.append(
                    {
                        "page_number": page_number,
                        "text": page_text or page_markdown,
                        "markdown": page_markdown or page_text,
                    }
                )
        return pages

    def _result(
        self,
        file_path: Path,
        document_id: str,
        file_type: str,
        text: str,
        markdown: str,
        pages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "document_id": document_id,
            "file_name": file_path.name,
            "file_type": file_type,
            "title": file_path.stem,
            "markdown": markdown,
            "text": text,
            "pages": pages,
            "metadata": {},
        }

