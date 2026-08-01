"""Review orchestration service."""

import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_log import AgentLog
from app.models.report import Report
from app.models.repository import Repository
from app.models.review import Review
from graph.state import ReviewState
from graph.workflow import ReviewWorkflow


class ReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.workflow = ReviewWorkflow()

    async def start_review(
        self,
        repository_id: UUID,
        user_id: UUID,
        review_type: str = "full",
        focus_areas: list[str] | None = None,
        custom_prompt: str | None = None,
    ) -> Review:
        repo_result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = repo_result.scalar_one_or_none()
        if not repo:
            raise ValueError("Repository not found")
        if repo.status != "ready":
            raise ValueError(f"Repository not ready for review (status: {repo.status})")

        review = Review(
            repository_id=repository_id,
            user_id=user_id,
            review_type=review_type,
            status="running",
        )
        self.db.add(review)
        await self.db.flush()

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

            async def progress_callback(state: ReviewState, current_stage: str) -> None:
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
                "repository", "architecture", "security", "performance",
                "testing", "documentation", "style", "dependencies",
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

            if result.get("overall_score"):
                repo.health_score = result["overall_score"]

        except Exception as e:
            review.status = "failed"
            review.summary = f"Review failed: {str(e)}"
            raise

        await self.db.flush()
        return review

    async def get_review(self, review_id: UUID) -> Review | None:
        result = await self.db.execute(select(Review).where(Review.id == review_id))
        return result.scalar_one_or_none()
