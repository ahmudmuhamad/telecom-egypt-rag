import streamlit as st
import sys
from pathlib import Path

# Add root directory to python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.retrieval.hybrid_retriever import HybridRetriever
from src.generation.answer_generator import AnswerGenerator
from src.logging.rag_logger import get_logger

logger = get_logger()

st.set_page_config(
    page_title="Telecom Egypt RAG Assistant",
    page_icon="📞",
    layout="wide"
)

st.title("📞 Telecom Egypt Customer Support Assistant")
st.write("Ask any question regarding Telecom Egypt (WE) services, devices, or FAQs.")

# Initialize session state for message history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display message history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# User Input
if query := st.chat_input("Enter your query (e.g. How to renew internet package?):"):
    with st.chat_message("user"):
        st.write(query)
    st.session_state.messages.append({"role": "user", "content": query})

    with st.chat_message("assistant"):
        with st.spinner("Retrieving relevant info and generating answer..."):
            # Placeholder RAG flow
            # retriever = HybridRetriever()
            # generator = AnswerGenerator(retriever)
            # response = generator.generate(query)
            response = f"This is a placeholder response for: '{query}'."
            st.write(response)
    st.session_state.messages.append({"role": "assistant", "content": response})\n