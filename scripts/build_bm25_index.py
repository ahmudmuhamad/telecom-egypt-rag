# Script to build BM25 Index
from src.logging.rag_logger import get_logger

logger = get_logger()

def main():
    logger.info("Building BM25 index...")
    # Todo: tokenize documents and build BM25 model
    logger.info("BM25 index built.")

if __name__ == "__main__":
    main()\n