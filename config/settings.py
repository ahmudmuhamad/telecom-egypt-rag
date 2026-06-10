from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / "config" / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "qwen3-embedding:4b"
    ollama_timeout_seconds: int = 600
    ollama_generation_num_predict: int = 256

    small_generation_model: str = "qwen3.5:0.8b"
    medium_generation_model: str = "qwen3.5:2b"
    large_generation_model: str = "qwen3:4b"
    default_generation_model: str = "qwen3.5:2b"
    enable_generation: bool = True
    generation_temperature: float = 0.0
    generation_max_context_sources: int = 5
    generation_max_context_chars: int = 6000
    generation_require_citations: bool = True
    generation_strict_grounding: bool = True
    generation_enable_model_fallback: bool = True
    generation_max_retries: int = 2
    context_snippet_max_chars: int = 1200
    context_compression_enabled: bool = True
    context_compression_mode: str = "deterministic"
    min_sources_for_answer: int = 1
    allow_no_source_answer: bool = False

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "telecom_all_sources_v1"

    kb_version: str = "telecom_egypt_kb_v1"
    embedding_provider: str = "ollama"
    embedding_model: str = "qwen3-embedding:4b"
    index_version: str = "telecom_all_sources_v1_qwen3_embedding_4b_ollama"

    chunk_size: int = 512
    chunk_overlap: int = 50

    data_dir: Path = Field(default=Path("data"))
    upload_dir: Path = Field(default=Path("data/uploads"))
    index_dir: Path = Field(default=Path("data/indexes"))
    log_dir: Path = Field(default=Path("data/logs"))
    kb_dir: Path = Field(default=Path("data/knowledge_base"))

    dense_top_k: int = 30
    bm25_top_k: int = 30
    final_top_k: int = 5
    rrf_k: int = 60

    enable_rule_based_routing: bool = True
    enable_llm_routing: bool = False
    enable_model_routing: bool = True
    enable_model_fallback: bool = True

    fast_dense_top_k: int = 10
    fast_bm25_top_k: int = 10
    fast_rerank_top_k: int = 10
    fast_final_top_k: int = 3

    standard_dense_top_k: int = 30
    standard_bm25_top_k: int = 30
    standard_rerank_top_k: int = 20
    standard_final_top_k: int = 5

    deep_dense_top_k: int = 50
    deep_bm25_top_k: int = 50
    deep_rerank_top_k: int = 30
    deep_final_top_k: int = 8

    enable_reranking: bool = True
    reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    reranker_fallback_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = 30
    rerank_batch_size: int = 4
    rerank_max_length: int = 1024
    rerank_device: str = "auto"
    rerank_strict_mode: bool = False
    rerank_load_timeout_seconds: int = 60

    enable_multi_query: bool = True
    multi_query_max_variants: int = 6

    enable_exact_cache: bool = True
    enable_semantic_cache: bool = True
    semantic_cache_threshold: float = 0.95
    semantic_cache_collection: str = "semantic_query_cache_v1"
    enable_prompt_cache: bool = True
    enable_embedding_cache: bool = True
    enable_context_compression: bool = True

    enable_prometheus: bool = True
    rag_metrics_host: str = "0.0.0.0"
    rag_metrics_port: int = 8001
    rag_metrics_namespace: str = "telecom_rag"
    enable_rag_jsonl_logging: bool = True

    rag_api_host: str = "0.0.0.0"
    rag_api_port: int = 8000
    streamlit_port: int = 8501

    def _resolve_project_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return ROOT_DIR / path

    def ensure_directories(self) -> None:
        for path in (self.log_dir, self.index_dir, self.upload_dir, self.kb_dir):
            self._resolve_project_path(path).mkdir(parents=True, exist_ok=True)


settings = Settings()

# Backward-compatible module constants for older placeholder modules in this repo.
OLLAMA_BASE_URL = settings.ollama_base_url
QDRANT_URL = settings.qdrant_url
QDRANT_HOST = settings.qdrant_url.removeprefix("http://").removeprefix("https://").split(":")[0]
QDRANT_PORT = 6333
DENSE_EMBEDDING_MODEL = settings.embedding_model
RERANKER_MODEL = settings.reranker_model
LLM_MODEL = settings.default_generation_model
LOG_LEVEL = "INFO"
ENABLE_PROMETHEUS = settings.enable_prometheus
PROMETHEUS_PORT = settings.rag_metrics_port
DATA_DIR = settings._resolve_project_path(settings.data_dir)
PROCESSED_DATA_DIR = DATA_DIR / "processed"
INDEXES_DIR = settings._resolve_project_path(settings.index_dir)
LOGS_DIR = settings._resolve_project_path(settings.log_dir)
PORT = settings.streamlit_port
DEBUG = False
