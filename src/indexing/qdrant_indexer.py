from src.logging.rag_logger import get_logger

logger = get_logger()

class QdrantIndexer:
    def __init__(self):
        pass

    def index_chunks(self, chunks):
        logger.info(f"Indexing {len(chunks)} chunks in Qdrant...")\n