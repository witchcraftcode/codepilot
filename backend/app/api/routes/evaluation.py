"""Evaluation API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.repository import Repository
from app.models.user import User
from app.schemas import EvaluationRequest, EvaluationResponse
from app.services.evaluation_service import EvaluationService

router = APIRouter(tags=["evaluation"])


@router.post("/evaluation", response_model=EvaluationResponse)
async def run_evaluation(
    body: EvaluationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    repo_result = await db.execute(
        select(Repository).where(Repository.id == body.repository_id, Repository.owner_id == user.id)
    )
    repo = repo_result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    service = EvaluationService(db)
    report = await service.evaluate_repository(
        body.repository_id,
        [item.model_dump() for item in body.queries],
        top_k=body.top_k,
        include_baseline=body.include_baseline,
    )
    return EvaluationResponse(report=report.to_dict(), markdown=report.to_markdown())
