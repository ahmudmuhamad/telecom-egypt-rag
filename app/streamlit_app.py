from __future__ import annotations

import html
import sys
import uuid
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.generation.answer_generator import AnswerGenerator  # noqa: E402
from src.ingestion.upload_loader import UploadProcessor  # noqa: E402
from src.retrieval.source_formatter import clean_user_visible_text  # noqa: E402
from src.services.metrics import (  # noqa: E402
    RAG_ACTIVE_SESSIONS,
    record_error,
    start_metrics_server_once,
)

SOURCE_MODE_OPTIONS = {
    "Official WE sources": "official",
    "Uploaded documents": "uploads",
    "Both": "both",
}
UPLOAD_TYPES = ["pdf", "docx", "txt", "html", "htm", "png", "jpg", "jpeg", "tiff", "tif"]


st.set_page_config(
    page_title="WE Intelligent Assistant",
    page_icon=":speech_balloon:",
    layout="centered",
)

start_metrics_server_once()


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.4rem;
            max-width: 860px;
        }
        .source-card {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 12px 14px;
            margin-top: 10px;
        }
        .source-title {
            font-weight: 650;
            margin-bottom: 4px;
        }
        .source-link {
            font-size: 0.92rem;
            text-decoration: none;
            overflow-wrap: anywhere;
        }
        .source-snippet {
            font-size: 0.92rem;
            margin-top: 8px;
            line-height: 1.45;
        }
        .footer-note {
            color: #6b7280;
            font-size: 0.86rem;
            margin-top: 30px;
            padding-top: 12px;
            border-top: 1px solid #f1f5f9;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner=False)
def get_generator() -> AnswerGenerator:
    return AnswerGenerator()


def extract_answer_body(answer_with_sources: str) -> str:
    text = answer_with_sources or ""
    marker = "\nSources:"
    if marker in text:
        return text.split(marker, 1)[0].strip()
    if text.strip().startswith("Sources:"):
        return ""
    return text.strip()


def clean_answer_text(text: str) -> str:
    return clean_user_visible_text(extract_answer_body(text)).strip()


def render_header() -> None:
    st.title("WE Intelligent Assistant")
    st.caption("Ask about WE services, packages, devices, and FAQs.")


def render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        return
    st.markdown("**Sources**")
    for source in sources:
        source_id = html.escape(str(source.get("source_id") or ""))
        if source.get("source_type") == "user_upload":
            label = str(source.get("citation_label") or "Uploaded document")
            label_html = html.escape(label).replace(" - ", " &mdash; ", 1).replace(" — ", " &mdash; ", 1)
            display_title = f"[{source_id}] {label_html}"
        else:
            title = html.escape(str(source.get("title") or "Telecom Egypt source"))
            source_name = html.escape(str(source.get("source_name") or "Telecom Egypt"))
            display_title = f"[{source_id}] {source_name} &mdash; {title}"
        url = html.escape(str(source.get("citation_url") or ""))
        link_html = f'<a class="source-link" href="{url}" target="_blank">{url}</a>' if url else ""
        st.markdown(
            f"""
            <div class="source-card">
                <div class="source-title">{display_title}</div>
                {link_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def ensure_messages() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "upload_session_id" not in st.session_state:
        st.session_state.upload_session_id = uuid.uuid4().hex
    if "uploaded_documents" not in st.session_state:
        st.session_state.uploaded_documents = []
    if "processed_upload_keys" not in st.session_state:
        st.session_state.processed_upload_keys = set()
    if "metrics_session_registered" not in st.session_state:
        try:
            RAG_ACTIVE_SESSIONS.inc()
        except Exception:
            pass
        st.session_state.metrics_session_registered = True


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message.get("content") or "")
            if message["role"] == "assistant":
                render_sources(message.get("sources") or [])


def clear_conversation() -> None:
    st.session_state.messages = []


def get_upload_processor() -> UploadProcessor:
    return UploadProcessor(st.session_state.upload_session_id)


def render_upload_controls() -> str:
    st.markdown("**Upload documents**")
    uploaded_files = st.file_uploader(
        "Supported: PDF, DOCX, TXT, HTML, PNG, JPG, JPEG, TIFF",
        type=UPLOAD_TYPES,
        accept_multiple_files=True,
        label_visibility="visible",
    )
    if uploaded_files:
        processor = get_upload_processor()
        for uploaded_file in uploaded_files:
            upload_key = f"{uploaded_file.name}:{uploaded_file.size}"
            if upload_key in st.session_state.processed_upload_keys:
                continue
            try:
                saved_path = processor.save_uploaded_file(uploaded_file)
                manifest = processor.process_file(saved_path)
                st.session_state.uploaded_documents.append(manifest)
                st.session_state.processed_upload_keys.add(upload_key)
                st.success(f"Uploaded and processed: {uploaded_file.name}")
            except Exception:
                st.error(f"Could not process {uploaded_file.name}. Please try another file.")

    if st.session_state.uploaded_documents:
        names = ", ".join(doc.get("file_name", "document") for doc in st.session_state.uploaded_documents)
        st.caption(f"Uploaded: {names}")
        if st.button("Clear uploaded documents", use_container_width=True):
            get_upload_processor().clear_session_uploads()
            st.session_state.uploaded_documents = []
            st.session_state.processed_upload_keys = set()
            st.rerun()

    selected_label = st.selectbox("Search in", options=list(SOURCE_MODE_OPTIONS.keys()), index=0)
    return SOURCE_MODE_OPTIONS[selected_label]


def main() -> None:
    apply_styles()
    ensure_messages()

    with st.sidebar:
        if st.button("Clear conversation", use_container_width=True):
            clear_conversation()
            st.rerun()
        st.caption("Answers are generated from the available official Telecom Egypt sources in this demo.")

    render_header()
    source_mode = render_upload_controls()
    render_history()

    prompt = st.chat_input("Ask about WE services, packages, devices, or FAQs...")
    if not prompt:
        st.markdown(
            '<div class="footer-note">Answers are generated from the available official Telecom Egypt sources in this demo.</div>',
            unsafe_allow_html=True,
        )
        return

    if source_mode == "uploads" and not st.session_state.uploaded_documents:
        st.warning("Please upload a document first.")
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching official WE sources..."):
            try:
                result = get_generator().answer(
                    prompt,
                    source_mode=source_mode,
                    upload_session_id=st.session_state.upload_session_id,
                )
                answer_text = clean_answer_text(
                    result.get("answer_with_sources") or result.get("answer") or ""
                )
                sources = result.get("sources") or []
                if not answer_text:
                    answer_text = "Sorry, I could not answer that right now. Please try again."
                    sources = []
            except Exception:
                try:
                    record_error("streamlit")
                except Exception:
                    pass
                answer_text = "Sorry, I could not answer that right now. Please try again."
                sources = []
        st.markdown(answer_text)
        render_sources(sources)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer_text,
            "sources": sources,
        }
    )


if __name__ == "__main__":
    main()