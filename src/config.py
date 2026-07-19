"""Corpus — Configuration via Pydantic Settings.

All environment variables are loaded here and made available
as typed, validated attributes. Grouped by service.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg2://rag_user:rag_password@localhost:5432/corpus_db",
        alias="POSTGRES_DATABASE_URL",
    )


class OpenSearchSettings(BaseSettings):
    """OpenSearch connection and index settings."""

    model_config = SettingsConfigDict(env_prefix="OPENSEARCH__", extra="ignore")

    host: str = "http://localhost:9200"
    index_name: str = "corpus-papers"
    chunk_index_name: str = "corpus-chunks"
    vector_dimension: int = 1024
    vector_space_type: str = "cosinesimil"
    rrf_pipeline_name: str = "hybrid-rrf-pipeline"
    max_text_size: int = 1_000_000


class RedisSettings(BaseSettings):
    """Redis connection settings."""

    model_config = SettingsConfigDict(env_prefix="REDIS__", extra="ignore")

    host: str = "localhost"
    port: int = 6379
    password: str = ""
    db: int = 0
    ttl_hours: int = 6

    @property
    def url(self) -> str:
        """Build a Redis URL for clients that accept one."""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class ArxivSettings(BaseSettings):
    """arXiv API configuration."""

    model_config = SettingsConfigDict(env_prefix="ARXIV__", extra="ignore")

    base_url: str = "https://export.arxiv.org/api/query"
    search_category: str = "cs.AI"
    max_results: int = 50
    rate_limit_delay: float = 3.0
    timeout_seconds: int = 30
    pdf_cache_dir: str = "./data/arxiv_pdfs"


class ChunkingSettings(BaseSettings):
    """Text chunking configuration."""

    model_config = SettingsConfigDict(env_prefix="CHUNKING__", extra="ignore")

    chunk_size: int = 500
    overlap_size: int = 75
    min_chunk_size: int = 100
    section_based: bool = True


class JinaSettings(BaseSettings):
    """Jina AI embeddings and reranker settings (legacy backend, kept for rollback)."""

    model_config = SettingsConfigDict(env_prefix="JINA", extra="ignore")

    api_key: str = Field(default="", alias="JINA_API_KEY")
    embedding_model: str = Field(default="jina-embeddings-v4", alias="JINA__EMBEDDING_MODEL")
    reranker_model: str = Field(default="jina-reranker-v2-base-multilingual", alias="JINA__RERANKER_MODEL")


class EmbeddingSettings(BaseSettings):
    """Embedding backend settings — local sentence-transformers by default."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING__", extra="ignore")

    backend: str = "local"  # "local" (sentence-transformers), "ollama" (quantized, fast), "jina" (legacy)
    model_name: str = "BAAI/bge-m3"
    ollama_model: str = "bge-m3"  # served by host Ollama when backend="ollama"
    device: str = "cpu"  # "cuda" only for offline reindex runs
    batch_size: int = 32
    max_length: int = 1024
    normalize: bool = True


class OllamaSettings(BaseSettings):
    """Ollama local LLM settings."""

    model_config = SettingsConfigDict(env_prefix="OLLAMA", extra="ignore")

    host: str = Field(default="http://localhost:11434", alias="OLLAMA_HOST")
    model: str = Field(default="qwen3:8b", alias="OLLAMA_MODEL")
    timeout: int = Field(default=300, alias="OLLAMA_TIMEOUT")


class LangfuseSettings(BaseSettings):
    """Langfuse tracing settings."""

    model_config = SettingsConfigDict(env_prefix="LANGFUSE", extra="ignore")

    enabled: bool = Field(default=True, alias="LANGFUSE_ENABLED")
    host: str = Field(default="http://localhost:3001", alias="LANGFUSE_HOST")
    public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")


class TelegramSettings(BaseSettings):
    """Telegram bot settings."""

    model_config = SettingsConfigDict(env_prefix="TELEGRAM__", extra="ignore")

    enabled: bool = False
    bot_token: str = ""


class PdfParserSettings(BaseSettings):
    """Docling and PDF parsing settings."""

    model_config = SettingsConfigDict(env_prefix="PDF_PARSER__", extra="ignore")

    max_file_size_mb: int = 200
    max_pages: int = 1000
    do_table_structure: bool = True


class RerankerSettings(BaseSettings):
    """Reranker configuration — pluggable backend."""

    model_config = SettingsConfigDict(env_prefix="RERANKER__", extra="ignore")

    enabled: bool = True
    backend: str = "local"  # "local" (cross-encoder), "jina" (legacy), "noop"
    model: str = "BAAI/bge-reranker-v2-m3"
    device: str = "cpu"
    max_length: int = 512
    batch_size: int = 8
    top_k: int = 8
    timeout: int = 30


class LiteLLMSettings(BaseSettings):
    """LiteLLM model routing settings."""

    model_config = SettingsConfigDict(env_prefix="LITELLM__", extra="ignore")

    default_model: str = "ollama/qwen3:8b"
    reasoning_model: str = "ollama/qwen3:8b"
    drafting_model: str = "ollama/qwen3:8b"
    fast_model: str = "ollama/llama3.2:3b"  # router/grader/rewrite — latency-critical roles
    timeout: int = 300
    max_retries: int = 2


class Settings(BaseSettings):
    """Root settings — aggregates all sub-settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    debug: bool = Field(default=True, alias="DEBUG")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    app_name: str = Field(default="corpus", alias="APP_NAME")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_key: str = Field(default="", alias="API_KEY")

    # Pipeline behavior
    enable_llm_verification: bool = Field(default=True, alias="ENABLE_LLM_VERIFICATION")
    semantic_cache_enabled: bool = Field(default=True, alias="SEMANTIC_CACHE_ENABLED")
    semantic_cache_threshold: float = Field(default=0.96, alias="SEMANTIC_CACHE_THRESHOLD")
    guardrails_max_query_chars: int = Field(default=2000, alias="GUARDRAILS_MAX_QUERY_CHARS")
    grading_max_chunks: int = Field(default=12, alias="GRADING_MAX_CHUNKS")
    generation_max_tokens: int = Field(default=4096, alias="GENERATION_MAX_TOKENS")
    model_autoselect: bool = Field(default=False, alias="MODEL_AUTOSELECT")
    model_ladder: str = Field(default="llama3.2:3b,llama3.2:1b", alias="MODEL_LADDER")
    zotero_local_url: str = Field(default="http://host.docker.internal:23119", alias="ZOTERO__LOCAL_URL")

    # Sub-settings (loaded from env as well)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    opensearch: OpenSearchSettings = Field(default_factory=OpenSearchSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    arxiv: ArxivSettings = Field(default_factory=ArxivSettings)
    pdf_parser: PdfParserSettings = Field(default_factory=PdfParserSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    jina: JinaSettings = Field(default_factory=JinaSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)
    reranker: RerankerSettings = Field(default_factory=RerankerSettings)
    litellm: LiteLLMSettings = Field(default_factory=LiteLLMSettings)


# Singleton — import this everywhere
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get the application settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
