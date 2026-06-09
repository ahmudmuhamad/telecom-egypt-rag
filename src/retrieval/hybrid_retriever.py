from src.retrieval.dense_retriever import DenseRetriever
from src.retrieval.bm25_retriever import BM25Retriever

class HybridRetriever:
    def __init__(self):
        self.dense = DenseRetriever()
        self.bm25 = BM25Retriever()

    def retrieve(self, query: str, top_k: int = 5, alpha: float = 0.5):
        # Merge vector and keyword scores
        return []\n