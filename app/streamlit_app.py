from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.generation.answer_generator import AnswerGenerator  # noqa: E402
from src.retrieval.source_formatter import clean_user_visible_text  # noqa: E402


st.set_page_config(
    page_title="WE Intelligent Assistant",
    page_icon="💬",
    layout="centered",
)


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
        title = html.escape(str(source.get("title") or "Telecom Egypt source"))
        source_name = html.escape(str(source.get("source_name") or "Telecom Egypt"))
        url = html.escape(str(source.get("citation_url") or ""))
        link_html = f'<a class="source-link" href="{url}" target="_blank">{url}</a>' if url else ""
        st.markdown(
            f"""
            <div class="source-card">
                <div class="source-title">[{source_id}] {source_name} &mdash; {title}</div>
                {link_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


def ensure_messages() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def render_history() -> None:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message.get("content") or "")
            if message["role"] == "assistant":
                render_sources(message.get("sources") or [])


def clear_conversation() -> None:
    st.session_state.messages = []


def main() -> None:
    apply_styles()
    ensure_messages()

    with st.sidebar:
        if st.button("Clear conversation", use_container_width=True):
            clear_conversation()
            st.rerun()
        st.caption("Answers are generated from the available official Telecom Egypt sources in this demo.")

    render_header()
    render_history()

    prompt = st.chat_input("Ask about WE services, packages, devices, or FAQs...")
    if not prompt:
        st.markdown(
            '<div class="footer-note">Answers are generated from the available official Telecom Egypt sources in this demo.</div>',
            unsafe_allow_html=True,
        )
        return

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Searching official WE sources..."):
            try:
                result = get_generator().answer(prompt, source_mode="official")
                answer_text = clean_answer_text(
                    result.get("answer_with_sources") or result.get("answer") or ""
                )
                sources = result.get("sources") or []
                if not answer_text:
                    answer_text = "Sorry, I could not answer that right now. Please try again."
                    sources = []
            except Exception:
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
