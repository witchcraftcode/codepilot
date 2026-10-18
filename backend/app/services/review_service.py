"""Review orchestration service."""

import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_log import AgentLog
from app.models.report import Report
from app.models.repository import Repository
from app.models.review import Review
from graph.state import ReviewState
from graph.workflow import ReviewWorkflow

ANALYSIS_RESULT_KEYS = {
    "repository": "repository_result",
    "architecture": "architecture_result",
    "security": "security_result",
    "performance": "performance_result",
    "testing": "testing_result",
    "documentation": "documentation_result",
    "style": "style_result",
    "dependencies": "dependency_result",
}


class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.workflow = ReviewWorkflow()

    @staticmethod
    async def fail_abandoned_pending_reviews(
        db: AsyncSession,
        *,
        include_running: bool = False,
    ) -> int:
        """Fail stale queued work, and optionally stale running work during recovery."""
        from sqlalchemy import update

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        statuses = ["pending", "running"] if include_running else ["pending"]
        result = await db.execute(
            update(Review)
            .where(Review.status.in_(statuses), Review.created_at < cutoff)
            .values(
                status="failed",
                summary=case(
                    (Review.status == "pending", "Review did not start before the worker stopped. Please retry."),
                    else_="Review was interrupted when the worker stopped. Please retry.",
                ),
                completed_at=datetime.now(timezone.utc),
            )
        )
        return result.rowcount or 0

    async def start_review(
        self,
        repository_id: UUID,
        user_id: UUID,
        review_type: str = "full",
        focus_areas: list[str] | None = None,
        custom_prompt: str | None = None,
        review_id: UUID | None = None,
    ) -> Review:
        repo_result = await self.db.execute(
            select(Repository).where(
                Repository.id == repository_id,
                Repository.owner_id == user_id,
            )
        )
        repo = repo_result.scalar_one_or_none()
        if not repo:
            raise ValueError("Repository not found")
        if repo.status != "ready":
            raise ValueError(
                f"Repository not ready for review (status: {repo.status})"
            )

        if review_id is not None:
            review_result = await self.db.execute(
                select(Review).where(
                    Review.id == review_id,
                    Review.repository_id == repository_id,
                    Review.user_id == user_id,
                ).with_for_update()
            )
            review = review_result.scalar_one_or_none()
            if not review:
                raise ValueError("Review not found for this user and repository")
            # Background task delivery can be retried. Never execute an already
            # claimed or terminal review twice (which would duplicate logs/reports).
            if review.status != "pending":
                return review
            review.status = "running"
        else:
            review = Review(
                repository_id=repository_id,
                user_id=user_id,
                review_type=review_type,
                status="running",
            )
            self.db.add(review)

        await self.db.flush()
        # Persist the claim before executing the graph. A duplicate background
        # delivery then observes running and exits instead of executing twice.
        await self.db.commit()

        start = time.time()
        try:
            initial_state: ReviewState = {
                "repository_id": str(repository_id),
                "review_id": str(review.id),
                "review_type": review_type,
                "user_request": custom_prompt or f"Perform a {review_type} review",
                "focus_areas": focus_areas or [],
                "agents_to_run": [],
                "execution_plan": "",
                "repo_metadata": {
                    "languages": repo.languages,
                    "frameworks": repo.frameworks,
                    "dependencies": repo.dependencies,
                    "file_count": repo.file_count,
                },
                "retrieved_context": [],
                "repository_result": None,
                "architecture_result": None,
                "security_result": None,
                "performance_result": None,
                "testing_result": None,
                "documentation_result": None,
                "style_result": None,
                "dependency_result": None,
                "overall_score": None,
                "progress_updates": [],
                "summary": None,
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
                "total_tokens": 0,
                "messages": [],
                "errors": [],
            }

            async def progress_callback(
                state: ReviewState, current_stage: str
            ) -> None:
                progress_entry = {
                    "stage": current_stage,
                    "message": f"Completed stage: {current_stage}",
                    "agents_to_run": state.get("agents_to_run"),
                    "execution_plan": state.get("execution_plan"),
                    "total_tokens": state.get("total_tokens", 0),
                }
                log = AgentLog(
                    review_id=review.id,
                    agent_name="progress",
                    status="running",
                    output=progress_entry,
                    findings=[],
                    score=None,
                    tokens_used=0,
                    duration_ms=0,
                )
                self.db.add(log)
                await self.db.flush()

            workflow = ReviewWorkflow(progress_callback=progress_callback)
            result = await workflow.run(initial_state)

            executed_agents = result.get("agents_to_run") or []
            analysis_results = []
            for name, result_key in ANALYSIS_RESULT_KEYS.items():
                agent_result = result.get(result_key)
                if name in executed_agents and isinstance(agent_result, dict):
                    if any(key in agent_result for key in ("score", "architecture_score", "performance_score")):
                        analysis_results.append(agent_result)
            if not analysis_results:
                raise RuntimeError("Review workflow completed without an analysis agent result")

            review.overall_score = result.get("overall_score")
            review.summary = result.get("summary")
            review.top_issues = result.get("top_issues")
            review.priority_fixes = result.get("priority_fixes")
            review.roadmap = result.get("roadmap")
            review.agents_executed = result.get("agents_to_run")
            review.tokens_used = result.get("total_tokens", 0)
            review.duration_ms = int((time.time() - start) * 1000)
            review.status = "completed"
            review.completed_at = datetime.now(timezone.utc)

            agent_names = [
                "repository",
                "architecture",
                "security",
                "performance",
                "testing",
                "documentation",
                "style",
                "dependencies",
            ]
            report_data = {}
            for name in agent_names:
                agent_result = result.get(f"{name}_result")
                if agent_result:
                    report_data[name] = agent_result
                    log = AgentLog(
                        review_id=review.id,
                        agent_name=name,
                        status="completed",
                        output=agent_result,
                        findings=agent_result.get("findings"),
                        score=agent_result.get("score"),
                        tokens_used=agent_result.get("tokens_used", 0),
                        duration_ms=agent_result.get("duration_ms"),
                    )
                    self.db.add(log)

            report = Report(
                review_id=review.id,
                architecture=report_data.get("architecture"),
                security=report_data.get("security"),
                performance=report_data.get("performance"),
                testing=report_data.get("testing"),
                documentation=report_data.get("documentation"),
                style=report_data.get("style"),
                dependencies=report_data.get("dependencies"),
                repository_overview=report_data.get("repository"),
            )
            self.db.add(report)

            if result.get("overall_score") is not None:
                repo.health_score = result["overall_score"]

        except Exception:
            review.status = "failed"
            review.summary = "Review failed. Check server logs for the underlying error."
            review.completed_at = datetime.now(timezone.utc)
            raise

        await self.db.flush()
        return review


    async def get_review(self, review_id: UUID) -> Review | None:
        result = await self.db.execute(select(Review).where(Review.id == review_id))
        return result.scalar_one_or_none()
