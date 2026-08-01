"""Application configuration with environment-based settings."""

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


class EmbeddingProvider(str, Enum):
    OPENAI = "openai"
    BGE = "bge"
    NOMIC = "nomic"
    VOYAGE = "voyage"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "CodePilot AI"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Database
    database_url: str = "postgresql+asyncpg://codepilot:codepilot@postgres:5432/codepilot"
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 3600

    # Vector store
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "code_chunks"
    vector_dimension: int = 1536

    # LLM
    llm_provider: LLMProvider = LLMProvider.OPENAI
    llm_model: str = "gpt-4.1"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096

    # Provider API keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Embeddings
    embedding_provider: EmbeddingProvider = EmbeddingProvider.OPENAI
    embedding_model: str = "text-embedding-3-small"
    # Batch size used when requesting embeddings from provider (helps throughput)
    embedding_batch_size: int = 64
    # Retry settings for transient provider/network errors
    embedding_max_retries: int = 3
    embedding_backoff_base: float = 0.5
    # How long to cache embeddings in Redis (days)
    embedding_cache_ttl_days: int = 7
    voyage_api_key: str = ""

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:3000/auth/callback"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Repository processing
    repo_clone_dir: str = "/tmp/codepilot/repos"
    max_repo_size_mb: int = 500
    chunk_max_tokens: int = 512
    supported_languages: list[str] = ["python", "javascript", "typescript", "java", "cpp", "go", "rust"]

    # Observability
    langsmith_api_key: str = ""
    langsmith_project: str = "codepilot-ai"
    langsmith_tracing: bool = True
    otel_exporter_endpoint: str = ""

    # MCP
    mcp_github_enabled: bool = True
    mcp_filesystem_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
