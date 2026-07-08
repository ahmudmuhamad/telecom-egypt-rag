import sys
sys.path.append('.')
from src.retrieval.dense_retriever import DenseRetriever

r = DenseRetriever()
q = "AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)"
results = r.search(q, top_k=5)
for res in results:
    print("TITLE:", res.get("title"))
    print("CONTENT:", res.get("content"))
    print("SCORE:", res.get("score"))
    print("---")
