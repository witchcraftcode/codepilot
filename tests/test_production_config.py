"""Production-only configuration guards without reading developer secrets."""

import pytest
from pydantic import ValidationError

from app.config import EmbeddingProvider, LLMProvider, Settings


def valid_production_configuration(**overrides):
    values = {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "database_url": "postgresql+asyncpg://user:password@db.example.com/codepilot",
        "redis_url": "redis://redis.example.com:6379/0",
        "qdrant_url": "https://vectors.example.com",
        "github_client_id": "test-client-id",
        "github_client_secret": "test-client-secret",
        "github_redirect_uri": "https://codepilot.example.com/api/v1/auth/callback",
        "jwt_secret": "a-test-only-secret-with-more-than-32-characters",
        "llm_provider": LLMProvider.OLLAMA,
        "llm_model": "llama3.2",
        "ollama_base_url": "https://models.example.com",
        "embedding_provider": EmbeddingProvider.BGE,
        "embedding_model": "BAAI/bge-m3",
        "vector_dimension": 1024,
    }
    values.update(overrides)
    return values


def test_production_rejects_the_development_jwt_secret():
    values = valid_production_configuration(jwt_secret="codepilot-dev-secret")

    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(**values)


def test_production_rejects_local_service_defaults():
    values = valid_production_configuration(redis_url="redis://localhost:6379")

    with pytest.raises(ValidationError, match="REDIS_URL"):
        Settings(**values)


def test_production_requires_credentials_for_selected_paid_provider():
    values = valid_production_configuration(
        llm_provider=LLMProvider.OPENAI,
        openai_api_key="",
        embedding_provider=EmbeddingProvider.BGE,
    )

    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(**values)


def test_valid_non_openai_production_configuration_is_accepted():
    settings = Settings(**valid_production_configuration())

    assert settings.llm_provider == LLMProvider.OLLAMA
    assert settings.embedding_provider == EmbeddingProvider.BGE
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_development_defaults_remain_available_only_outside_production():
    settings = Settings(_env_file=None, app_env="development")

    assert settings.jwt_secret == "codepilot-dev-secret"
    assert settings.llm_provider == LLMProvider.OPENAI


def test_production_rejects_embedding_dimension_mismatch():
    with pytest.raises(ValidationError, match="VECTOR_DIMENSION"):
        Settings(**valid_production_configuration(vector_dimension=1536))


def test_production_rejects_unsupported_embedding_model_for_provider():
    with pytest.raises(ValidationError, match="Unsupported embedding provider/model"):
        Settings(
            **valid_production_configuration(
                embedding_provider=EmbeddingProvider.BGE,
                embedding_model="text-embedding-3-small",
            )
        )
