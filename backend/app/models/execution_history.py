"""Execution history for LangGraph workflow runs."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class ExecutionHistory(Base):
    __tablename__ = "execution_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id"), index=True)
    workflow_name: Mapped[str] = mapped_column(String(100))
    graph_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    nodes_executed: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
