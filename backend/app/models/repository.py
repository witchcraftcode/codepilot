"""Repository model for indexed GitHub repositories."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    github_url: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    languages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    frameworks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dependencies: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, indexing, ready, error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner = relationship("User", back_populates="repositories")
    reviews = relationship("Review", back_populates="repository", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="repository", cascade="all, delete-orphan")
    embeddings = relationship("EmbeddingRecord", back_populates="repository", cascade="all, delete-orphan")
    file_hashes = relationship("RepositoryFileHash", back_populates="repository", cascade="all, delete-orphan")
