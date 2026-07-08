import sys
import asyncio
sys.path.append('.')
from src.retrieval.embedder import QdrantEmbedder

async def main():
    embedder = QdrantEmbedder()
    q1 = "Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 1)"
    q2 = "Tell me more about AC1300 Whole Home Mesh Wi-Fi System (Pack of 3)"
    emb1 = await embedder.embed_query(q1)
    emb2 = await embedder.embed_query(q2)
    
    # Cosine similarity
    import numpy as np
    emb1 = np.array(emb1)
    emb2 = np.array(emb2)
    similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
    print(f"Similarity: {similarity}")

if __name__ == "__main__":
    asyncio.run(main())
