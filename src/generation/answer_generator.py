from src.generation.prompt_templates import SYSTEM_PROMPT, RAG_PROMPT_TEMPLATE

class AnswerGenerator:
    def __init__(self, retriever):
        self.retriever = retriever

    def generate(self, query: str) -> str:
        context = self.retriever.retrieve(query)
        # Call Ollama/LLM
        return "Response text placeholder."\n