from functools import lru_cache
from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class Settings(BaseSettings):
    # App
    app_name: str = "CodePilot"
    debug: bool = True

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/codepilot",
        alias="DATABASE_URL",
    )

    database_echo: bool = Field(
        default=False,
        alias="DATABASE_ECHO",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        alias="REDIS_URL",
    )

    # Qdrant
    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
    )

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
    
    model_config = SettingsConfigDict(
        env_file=".env",
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

    # Qdrant Cloud
    qdrant_url: str = Field(
        default="http://localhost:6333",
        alias="QDRANT_URL",
    )

    qdrant_api_key: str = Field(
        default="",
        alias="QDRANT_API_KEY",
    )

    # LLM
    llm_provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        alias="LLM_PROVIDER",
    )
    llm_model: str = Field(default="gpt-4.1", alias="LLM_MODEL")

    # Anthropic
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # LangSmith
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")

    # OpenTelemetry
    otel_exporter_endpoint: str = Field(
        default="",
        alias="OTEL_EXPORTER_ENDPOINT",
    )

    otel_service_name: str = Field(
        default="codepilot-backend",
        alias="OTEL_SERVICE_NAME",
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()