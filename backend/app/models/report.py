"""Detailed review report with per-agent results."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reviews.id"), unique=True)
    architecture: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    security: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    performance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    testing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    documentation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    style: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dependencies: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    repository_overview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    architecture_diagram: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    review = relationship("Review", back_populates="report")
