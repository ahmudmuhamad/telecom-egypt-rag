import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.generation.citation_parser import extract_required_query_entities, has_entity_mismatch

query = "Tell me about MisrLeX project"
entities = extract_required_query_entities(query)
print(f"Entities: {entities}")

answer = "MisrLeX is an Egyptian Legal RAG Platform."
sources = [
    {
        "source_id": 1,
        "title": "Ahmed_Ahmed_2025.pdf",
        "content": "MisrLeX - Egyptian Legal RAG Platform Project Link - Developed a Retrieval-Augmented Generation (RAG) platform",
        "snippet": "MisrLeX - Egyptian Legal RAG Platform Project Link",
        "metadata": {},
    }
]
citation_ids = {1}
print(f"has_entity_mismatch: {has_entity_mismatch(query, answer, sources, citation_ids)}")
