# Script to run retrieval evaluation
from src.logging.rag_logger import get_logger

logger = get_logger()

def main():
    logger.info("Running retrieval evaluation...")
    # Todo: query retriever and measure recall, precision, mrr
    logger.info("Retrieval evaluation completed.")

if __name__ == "__main__":
    main()\n