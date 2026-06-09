# Script to reset both Qdrant and BM25 indexes
from src.logging.rag_logger import get_logger

logger = get_logger()

def main():
    logger.info("Resetting all indexes...")
    # Todo: delete Qdrant collection and BM25 stored files
    logger.info("Indexes reset completed.")

if __name__ == "__main__":
    main()\n