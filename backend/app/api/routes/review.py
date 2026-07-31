"""Review API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.agent_log import AgentLog
from app.models.report import Report
from app.models.review import Review
from app.models.user import User
from app.schemas import (
    AgentResultResponse,
    DocumentationRequest,
    ExplainFunctionRequest,
    FindingResponse,
    PRReviewRequest,
    ReviewCreate,
    ReviewDetailResponse,
    ReviewListResponse,
    ReviewResponse,
    SecurityAuditRequest,
    TestGenerationRequest,
)
from app.services.review_service import ReviewService

router = APIRouter(tags=["review"])


async def _run_review_background(review_id: UUID, repository_id: UUID, user_id: UUID, review_type: str, db_url: str, focus: list | None, prompt: str | None) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    engine = create_async_engine(db_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        service = ReviewService(session)
        await service.start_review(repository_id, user_id, review_type, focus, prompt)
        await session.commit()


@router.post("/review", response_model=ReviewResponse, status_code=201)
async def create_review(
    body: ReviewCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    review = Review(
        repository_id=body.repository_id,
        user_id=user.id,
        review_type=body.review_type.value,
        status="pending",
    )
    db.add(review)
    await db.flush()

    from app.config import get_settings

    settings = get_settings()
    background_tasks.add_task(
        _run_review_background,
        review.id,
        body.repository_id,
        user.id,
        body.review_type.value,
        settings.database_url,
        body.focus_areas,
        body.custom_prompt,
    )

    return review


@router.get("/review/{review_id}", response_model=ReviewDetailResponse)
async def get_review(
    review_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Review).where(Review.id == review_id, Review.user_id == user.id)
    )
    review = result.scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    logs_result = await db.execute(select(AgentLog).where(AgentLog.review_id == review_id))
    logs = logs_result.scalars().all()

    report_result = await db.execute(select(Report).where(Report.review_id == review_id))
    report = report_result.scalar_one_or_none()

    agent_results = []
    for log in logs:
        findings = []
        if log.findings:
            for f in log.findings:
                findings.append(FindingResponse(**f))
        agent_results.append(
            AgentResultResponse(
                agent_name=log.agent_name,
                score=log.score,
                findings=findings,
                summary=log.output.get("summary") if log.output else None,
                duration_ms=log.duration_ms,
            )
        )

    return ReviewDetailResponse(
        **ReviewResponse.model_validate(review).model_dump(),
        agent_results=agent_results,
        report={
            "architecture": report.architecture if report else None,
            "security": report.security if report else None,
            "performance": report.performance if report else None,
            "testing": report.testing if report else None,
            "documentation": report.documentation if report else None,
            "style": report.style if report else None,
            "dependencies": report.dependencies if report else None,
        } if report else None,
    )


@router.get("/history", response_model=ReviewListResponse)
async def get_history(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    repository_id: UUID | None = None,
    skip: int = 0,
    limit: int = 20,
):
    query = select(Review).where(Review.user_id == user.id)
    count_query = select(func.count()).select_from(Review).where(Review.user_id == user.id)
    if repository_id:
        query = query.where(Review.repository_id == repository_id)
        count_query = count_query.where(Review.repository_id == repository_id)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(Review.created_at.desc()).offset(skip).limit(limit))
    reviews = result.scalars().all()
    return ReviewListResponse(reviews=reviews, total=total)


@router.post("/security", response_model=ReviewResponse, status_code=201)
async def security_audit(
    body: SecurityAuditRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    return await create_review(
        ReviewCreate(repository_id=body.repository_id, review_type="security"),
        background_tasks,
        db,
        user,
    )


@router.post("/tests")
async def generate_tests(
    body: TestGenerationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    from app.services.llm_factory import get_llm
    from vectorstore.qdrant_store import VectorStore

    store = VectorStore()
    query = f"function {body.function_name}" if body.function_name else body.file_path
    chunks = await store.search(query=query, repository_id=str(body.repository_id), limit=3)

    context = "\n".join(c["content"] for c in chunks)
    llm = get_llm()
    from langchain_core.messages import HumanMessage, SystemMessage

    framework = body.framework or "pytest"
    response = await llm.ainvoke([
        SystemMessage(content=f"You are a test generation expert. Generate {framework} unit tests."),
        HumanMessage(content=f"Generate tests for:\n{context}"),
    ])
    return {"tests": str(response.content), "framework": framework}


@router.post("/documentation")
async def generate_documentation(
    body: DocumentationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    from app.services.llm_factory import get_llm
    from vectorstore.qdrant_store import VectorStore

    store = VectorStore()
    query = body.file_path or "readme documentation overview"
    chunks = await store.search(query=query, repository_id=str(body.repository_id), limit=5)
    context = "\n".join(c["content"] for c in chunks)

    llm = get_llm()
    from langchain_core.messages import HumanMessage, SystemMessage

    response = await llm.ainvoke([
        SystemMessage(content=f"Generate {body.target} documentation for this codebase."),
        HumanMessage(content=context),
    ])
    return {"documentation": str(response.content), "target": body.target}


@router.post("/explain")
async def explain_function(
    body: ExplainFunctionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    from app.services.llm_factory import get_llm
    from vectorstore.qdrant_store import VectorStore

    store = VectorStore()
    chunks = await store.search(
        query=f"{body.function_name} in {body.file_path}",
        repository_id=str(body.repository_id),
        limit=3,
    )
    context = "\n".join(c["content"] for c in chunks)

    llm = get_llm()
    from langchain_core.messages import HumanMessage, SystemMessage

    response = await llm.ainvoke([
        SystemMessage(content="Explain this function: purpose, inputs, outputs, complexity, and edge cases."),
        HumanMessage(content=f"Function: {body.function_name}\nFile: {body.file_path}\n\n{context}"),
    ])
    return {"explanation": str(response.content)}


@router.post("/pr-review")
async def review_pull_request(
    body: PRReviewRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    from app.services.llm_factory import get_llm
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = get_llm()
    response = await llm.ainvoke([
        SystemMessage(content="Review this pull request diff. Identify bugs, security issues, style problems, and suggest improvements."),
        HumanMessage(content=f"Title: {body.pr_title}\nDescription: {body.pr_description}\n\nDiff:\n{body.pr_diff[:8000]}"),
    ])
    return {"review": str(response.content)}
