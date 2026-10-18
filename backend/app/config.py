from functools import lru_cache
from enum import Enum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
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
    # App
    app_name: str = "CodePilot"
    app_env: Literal["development", "test", "production"] = Field(
        default="development",
        alias="APP_ENV",
    )
    debug: bool = Field(default=True, alias="DEBUG")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/codepilot",
        alias="DATABASE_URL",
    )

    database_echo: bool = Field(
        default=False,
        alias="DATABASE_ECHO",
    )
    health_check_timeout_seconds: float = Field(
        default=2.0,
        alias="HEALTH_CHECK_TIMEOUT_SECONDS",
        gt=0,
        le=30,
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        alias="REDIS_URL",
    )
    cache_ttl_seconds: int = Field(default=3600, alias="CACHE_TTL_SECONDS")

    # OpenAI
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # GitHub
    github_client_id: str = Field(default="", alias="GITHUB_CLIENT_ID")
    github_client_secret: str = Field(default="", alias="GITHUB_CLIENT_SECRET")
    github_redirect_uri: str = Field(
        default="http://localhost:8000/api/v1/auth/callback",
        alias="GITHUB_REDIRECT_URI",
    )

    # JWT
    jwt_secret: str = Field(default="codepilot-dev-secret", alias="JWT_SECRET")

    jwt_expire_minutes: int = Field(
        default=60,
        alias="JWT_EXPIRE_MINUTES",
    )

    jwt_algorithm: str = Field(
        default="HS256",
        alias="JWT_ALGORITHM",
    )
    
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
        populate_by_name=True,
    )

    # API
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    # App version
    app_version: str = "0.1.0"

    # CORS
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        alias="CORS_ORIGINS",
    )

    # Qdrant
    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
    )

    qdrant_api_key: str = Field(
        default="",
        alias="QDRANT_API_KEY",
    )
    qdrant_collection: str = Field(default="codepilot_chunks", alias="QDRANT_COLLECTION")

    # LLM
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        alias="LLM_PROVIDER",
    )
    llm_model: str = Field(default="gpt-4.1", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=4096, alias="LLM_MAX_TOKENS")

    # Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")

    # Embeddings
    embedding_provider: EmbeddingProvider = Field(
        default=EmbeddingProvider.OPENAI,
        alias="EMBEDDING_PROVIDER",
    )
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_batch_size: int = Field(default=64, alias="EMBEDDING_BATCH_SIZE")
    embedding_max_retries: int = Field(default=3, alias="EMBEDDING_MAX_RETRIES")
    embedding_backoff_base: float = Field(default=0.5, alias="EMBEDDING_BACKOFF_BASE")
    repository_index_batch_size: int = Field(default=25, alias="REPOSITORY_INDEX_BATCH_SIZE")
    vector_dimension: int = Field(default=1536, alias="VECTOR_DIMENSION")
    voyage_api_key: str = Field(default="", alias="VOYAGE_API_KEY")

    # Repository indexing
    repo_clone_dir: str = Field(default="/tmp/codepilot-repos", alias="REPO_CLONE_DIR")

    # LangSmith
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="codepilot-ai", alias="LANGSMITH_PROJECT")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # OpenTelemetry
    otel_exporter_endpoint: str = Field(
        default="",
        alias="OTEL_EXPORTER_ENDPOINT",
    )

    otel_service_name: str = Field(
        default="codepilot-backend",
        alias="OTEL_SERVICE_NAME",
    )

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.app_env != "production":
            return self

        if self.debug:
            raise ValueError("DEBUG must be false when APP_ENV=production")
        if (
            len(self.jwt_secret) < 32
            or self.jwt_secret == "codepilot-dev-secret"
            or self.jwt_secret.lower() in {"changeme", "change-me", "secret"}
        ):
            raise ValueError("JWT_SECRET must be a unique secret of at least 32 characters")

        for env_name, configured_url in (
            ("DATABASE_URL", self.database_url),
            ("REDIS_URL", self.redis_url),
            ("QDRANT_URL", self.qdrant_url),
        ):
            host = urlsplit(configured_url).hostname
            if not host or host.casefold() in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(f"{env_name} must point to a configured production service")

        if not self.github_client_id or not self.github_client_secret:
            raise ValueError("GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET are required in production")
        if urlsplit(self.github_redirect_uri).scheme != "https":
            raise ValueError("GITHUB_REDIRECT_URI must use HTTPS in production")

        provider_credentials = {
            LLMProvider.OPENAI: ("OPENAI_API_KEY", self.openai_api_key),
            LLMProvider.ANTHROPIC: ("ANTHROPIC_API_KEY", self.anthropic_api_key),
            LLMProvider.GEMINI: ("GOOGLE_API_KEY", self.google_api_key),
            LLMProvider.DEEPSEEK: ("DEEPSEEK_API_KEY", self.deepseek_api_key),
        }
        if self.llm_provider in provider_credentials:
            name, value = provider_credentials[self.llm_provider]
            if not value:
                raise ValueError(f"{name} is required for the configured LLM_PROVIDER")
        elif self.llm_provider == LLMProvider.OLLAMA:
            host = urlsplit(self.ollama_base_url).hostname
            if not host or host.casefold() in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("OLLAMA_BASE_URL must point to a reachable production service")

        if self.embedding_provider == EmbeddingProvider.OPENAI and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the configured EMBEDDING_PROVIDER")
        if self.embedding_provider == EmbeddingProvider.VOYAGE and not self.voyage_api_key:
            raise ValueError("VOYAGE_API_KEY is required for the configured EMBEDDING_PROVIDER")

        supported_embedding_models = {
            (EmbeddingProvider.BGE, "BAAI/bge-m3"): 1024,
            (EmbeddingProvider.NOMIC, "nomic-ai/nomic-embed-text-v1.5"): 768,
            (EmbeddingProvider.OPENAI, "text-embedding-3-small"): 1536,
            (EmbeddingProvider.OPENAI, "text-embedding-3-large"): 3072,
            (EmbeddingProvider.OPENAI, "text-embedding-ada-002"): 1536,
            (EmbeddingProvider.VOYAGE, "voyage-code-2"): 1536,
        }
        expected_dimension = supported_embedding_models.get(
            (self.embedding_provider, self.embedding_model)
        )
        if expected_dimension is None:
            raise ValueError(
                "Unsupported embedding provider/model combination; use a supported model with a known vector dimension"
            )
        if self.vector_dimension != expected_dimension:
            raise ValueError(
                f"VECTOR_DIMENSION must be {expected_dimension} for the configured EMBEDDING_PROVIDER/model"
            )

        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
