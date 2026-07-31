"""Configurable embedding provider factory."""

from langchain_core.embeddings import Embeddings

from app.config import EmbeddingProvider, get_settings


def get_embeddings() -> Embeddings:
    settings = get_settings()

    if settings.embedding_provider == EmbeddingProvider.OPENAI:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key or None,
        )

    if settings.embedding_provider == EmbeddingProvider.BGE:
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

    if settings.embedding_provider == EmbeddingProvider.NOMIC:
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name="nomic-ai/nomic-embed-text-v1.5", model_kwargs={"trust_remote_code": True})

    if settings.embedding_provider == EmbeddingProvider.VOYAGE:
        from langchain_voyageai import VoyageAIEmbeddings

        return VoyageAIEmbeddings(
            model=settings.embedding_model or "voyage-code-2",
            voyage_api_key=settings.voyage_api_key or None,
        )

    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")
