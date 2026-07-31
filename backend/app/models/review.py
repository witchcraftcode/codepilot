"""Review model for agent-generated code reviews."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("repositories.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    review_type: Mapped[str] = mapped_column(String(50), default="full")  # full, security, performance, etc.
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, running, completed, failed
    overall_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agents_executed: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    priority_fixes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    roadmap: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository = relationship("Repository", back_populates="reviews")
    user = relationship("User", back_populates="reviews")
    agent_logs = relationship("AgentLog", back_populates="review", cascade="all, delete-orphan")
    report = relationship("Report", back_populates="review", uselist=False, cascade="all, delete-orphan")
    feedback = relationship("ReviewFeedback", back_populates="review", cascade="all, delete-orphan")
