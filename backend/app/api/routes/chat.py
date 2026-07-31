"""Chat and feedback API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.feedback import ReviewFeedback
from app.models.repository import Repository
from app.models.user import User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    FeedbackCreate,
    HealthScoreBreakdown,
    ScoresResponse,
    ChatContextRequest,
    ChatContextResponse,
)
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService
from sqlalchemy import select

router = APIRouter(tags=["chat"])


@router.post("/context", response_model=ChatContextResponse)
async def retrieve_context(
    body: ChatContextRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    # validate repository ownership
    result = await db.execute(select(Repository).where(Repository.id == body.repository_id, Repository.owner_id == user.id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    service = RetrievalService()
    data = await service.retrieve(body.repository_id, body.question, k=body.k or 5, chunk_types=body.chunk_types, language=body.language)

    retrieved = []
    for r in data["retrieved"]:
        retrieved.append(
            {
                "file_path": r.get("file_path"),
                "chunk_type": r.get("chunk_type"),
                "language": r.get("language"),
                "symbol_name": r.get("symbol_name"),
                "content": r.get("content"),
                "start_line": r.get("start_line"),
                "end_line": r.get("end_line"),
                "score": r.get("score"),
            }
        )

    return ChatContextResponse(repository_id=body.repository_id, question=body.question, retrieved=retrieved, latency_ms=data["latency_ms"])



@router.post("/chat", response_model=ChatResponse)
async def chat_with_repository(
    body: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    service = ChatService(db)
    result = await service.chat(body.repository_id, user.id, body.message, body.conversation_id)
    return ChatResponse(**result)


@router.post("/feedback", status_code=201)
async def submit_feedback(
    body: FeedbackCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    feedback = ReviewFeedback(
        review_id=body.review_id,
        user_id=user.id,
        finding_id=body.finding_id,
        agent_name=body.agent_name,
        accepted=body.accepted,
        comment=body.comment,
    )
    db.add(feedback)
    await db.flush()
    return {"status": "ok", "id": str(feedback.id)}


@router.get("/scores/{repository_id}", response_model=ScoresResponse)
async def get_scores(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    from app.models.report import Report
    from app.models.review import Review

    repo_result = await db.execute(
        select(Repository).where(Repository.id == repository_id, Repository.owner_id == user.id)
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    review_result = await db.execute(
        select(Review)
        .where(Review.repository_id == repository_id, Review.status == "completed")
        .order_by(Review.completed_at.desc())
        .limit(1)
    )
    review = review_result.scalar_one_or_none()

    scores = HealthScoreBreakdown(
        security=70, performance=70, architecture=70,
        documentation=70, testing=70, maintainability=70,
        overall=repo.health_score or 70,
    )

    if review:
        report_result = await db.execute(select(Report).where(Report.review_id == review.id))
        report = report_result.scalar_one_or_none()
        if report:
            scores = HealthScoreBreakdown(
                security=report.security.get("score", 70) if report.security else 70,
                performance=report.performance.get("score", 70) if report.performance else 70,
                architecture=report.architecture.get("score", 70) if report.architecture else 70,
                documentation=report.documentation.get("score", 70) if report.documentation else 70,
                testing=report.testing.get("score", 70) if report.testing else 70,
                maintainability=report.style.get("score", 70) if report.style else 70,
                overall=review.overall_score or 70,
            )

    return ScoresResponse(
        repository_id=repository_id,
        health_score=scores,
        last_review_at=review.completed_at if review else None,
    )
