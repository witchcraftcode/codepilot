"""Pull request review orchestration service."""

import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.specialized import (
    ArchitectureAgent,
    DependencyAgent,
    DocumentationAgent,
    PerformanceAgent,
    PlannerAgent,
    SecurityAgent,
    StyleAgent,
    SummaryAgent,
    TestingAgent,
)
from app.models.agent_log import AgentLog
from app.models.pr_review_comment import PRReviewComment
from app.models.repository import Repository
from app.models.review import Review
from app.services.github_service import GitHubService, PullRequestData
from graph.state import ReviewState
from graph.workflow import AGENT_NODES
from parsers.diff_parser import build_context_chunks, parse_unified_diff
from vectorstore.qdrant_store import VectorStore

PR_AGENT_CLASSES = {
    "security": SecurityAgent,
    "performance": PerformanceAgent,
    "testing": TestingAgent,
    "style": StyleAgent,
    "architecture": ArchitectureAgent,
    "documentation": DocumentationAgent,
    "dependencies": DependencyAgent,
}

DEFAULT_CONFIDENCE = {
    "critical": 0.9,
    "high": 0.8,
    "medium": 0.7,
    "low": 0.6,
    "info": 0.5,
}


class PRReviewService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.vector_store = VectorStore()

    async def review_pull_request(
        self,
        repository: str,
        pull_request_number: int,
        user_id: UUID,
        access_token: str | None = None,
        repository_id: UUID | None = None,
    ) -> tuple[Review, list[str]]:
        """Run the full PR review pipeline and persist results."""
        github = GitHubService(access_token=access_token)
        owner, repo_name = github.parse_repository(repository)
        full_name = f"{owner}/{repo_name}"

        if repository_id is None:
            repo_result = await self.db.execute(
                select(Repository).where(
                    Repository.full_name == full_name,
                    Repository.owner_id == user_id,
                )
            )
            matched = repo_result.scalar_one_or_none()
            if matched:
                repository_id = matched.id

        pr_data = await github.fetch_pull_request(owner, repo_name, pull_request_number)
        changed_files = parse_unified_diff(pr_data.diff)
        diff_context = build_context_chunks(changed_files)
        repo_context = await self._retrieve_repo_context(repository_id, diff_context)

        review = Review(
            repository_id=repository_id,
            user_id=user_id,
            review_type="pull_request",
            status="running",
            pr_number=pr_data.number,
            pr_title=pr_data.title,
            pr_description=pr_data.body,
            pr_url=pr_data.html_url,
            base_branch=pr_data.base_branch,
            head_branch=pr_data.head_branch,
        )
        self.db.add(review)
        await self.db.flush()

        start = time.time()
        try:
            result = await self._run_pipeline(
                review=review,
                pr_data=pr_data,
                diff_context=diff_context,
                repo_context=repo_context,
                repository_id=repository_id,
                changed_file_count=len(changed_files),
            )
            comments = self._build_comments(result)
            for comment in comments:
                self.db.add(comment)

            review.overall_score = result.get("overall_score")
            review.summary = result.get("summary")
            review.top_issues = result.get("top_issues")
            review.priority_fixes = result.get("priority_fixes")
            review.agents_executed = result.get("agents_to_run")
            review.tokens_used = result.get("total_tokens", 0)
            review.duration_ms = int((time.time() - start) * 1000)
            review.status = "completed"
            review.completed_at = datetime.now(timezone.utc)

            await self._persist_agent_logs(review.id, result)
        except Exception as exc:
            review.status = "failed"
            review.summary = f"PR review failed: {exc}"
            review.duration_ms = int((time.time() - start) * 1000)
            review.completed_at = datetime.now(timezone.utc)
            await self.db.flush()

        await self.db.flush()
        changed_file_names = [
            f["filename"] for f in pr_data.files if f.get("filename")
        ] or [cf.file_path for cf in changed_files]
        return review, changed_file_names

    async def _retrieve_repo_context(
        self,
        repository_id: UUID | None,
        diff_context: list[dict],
    ) -> list[dict]:
        """Retrieve indexed repository context for changed files."""
        if not repository_id:
            return []

        seen: set[str] = set()
        extra: list[dict] = []
        for chunk in diff_context:
            file_path = chunk.get("file_path")
            if not file_path or file_path in seen:
                continue
            seen.add(file_path)
            results = await self.vector_store.search(
                query=f"file {file_path}",
                repository_id=str(repository_id),
                limit=3,
            )
            for r in results:
                key = f"{r.get('file_path')}:{r.get('symbol_name', '')}"
                if key not in seen:
                    seen.add(key)
                    extra.append(r)
        return extra

    async def _run_pipeline(
        self,
        review: Review,
        pr_data: PullRequestData,
        diff_context: list[dict],
        repo_context: list[dict],
        repository_id: UUID | None,
        changed_file_count: int,
    ) -> dict:
        """Execute planner, specialized agents, and summary."""
        combined_context = diff_context + repo_context
        repo_metadata = await self._get_repo_metadata(repository_id)
        repo_metadata["changed_files"] = changed_file_count
        repo_metadata["pr_files"] = [f.get("filename") for f in pr_data.files]

        initial_state: ReviewState = {
            "repository_id": str(repository_id) if repository_id else "pr-review",
            "review_id": str(review.id),
            "review_type": "pull_request",
            "user_request": (
                f"Review pull request #{pr_data.number}: {pr_data.title}\n\n"
                f"{pr_data.body or ''}\n\n"
                f"Changed files: {changed_file_count}"
            ),
            "focus_areas": [],
            "agents_to_run": [],
            "execution_plan": "",
            "repo_metadata": repo_metadata,
            "retrieved_context": combined_context,
            "diff_context": diff_context,
            "repository_context": repo_context,
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

        planner = PlannerAgent()
        plan = await planner.plan(initial_state)
        if isinstance(plan, dict):
            agents = [a["name"] for a in plan.get("agents", [])]
            initial_state["execution_plan"] = plan.get("summary", "")
        else:
            agents = list(plan)
            initial_state["execution_plan"] = f"Executing: {', '.join(agents)}"

        if "summary" not in agents:
            agents.append("summary")
        initial_state["agents_to_run"] = agents

        total_tokens = 0
        agent_results: list[dict] = []

        for agent_name in agents:
            if agent_name == "summary":
                continue
            if agent_name not in initial_state["agents_to_run"]:
                continue

            agent_cls = PR_AGENT_CLASSES.get(agent_name)
            if agent_cls is None:
                continue

            agent = agent_cls()
            result = await agent.run(initial_state)
            result_key = f"{agent_name}_result"
            initial_state[result_key] = result  # type: ignore[literal-required]
            total_tokens += result.get("tokens_used", 0)
            agent_results.append(result)

        summary_agent = SummaryAgent()
        summary = await summary_agent.summarize(initial_state, agent_results)
        initial_state.update(summary)
        initial_state["total_tokens"] = total_tokens

        return dict(initial_state)

    async def _get_repo_metadata(self, repository_id: UUID | None) -> dict:
        if not repository_id:
            return {"languages": {}, "frameworks": [], "dependencies": {}, "file_count": 0}

        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = result.scalar_one_or_none()
        if not repo:
            return {"languages": {}, "frameworks": [], "dependencies": {}, "file_count": 0}

        return {
            "languages": repo.languages,
            "frameworks": repo.frameworks,
            "dependencies": repo.dependencies,
            "file_count": repo.file_count,
        }

    def _normalize_finding(self, finding: dict, agent_name: str) -> dict | None:
        file_path = finding.get("file_path")
        line_number = finding.get("line_number")
        if not file_path or line_number is None:
            return None

        severity = finding.get("severity", "info")
        confidence = finding.get("confidence")
        if confidence is None:
            confidence = DEFAULT_CONFIDENCE.get(severity, 0.5)

        explanation = finding.get("description") or finding.get("title") or ""
        suggested_fix = (
            finding.get("suggestion")
            or finding.get("suggested_fix")
            or finding.get("suggested_optimization")
        )

        return {
            "file_path": file_path,
            "line_number": int(line_number),
            "severity": severity,
            "explanation": explanation,
            "suggested_fix": suggested_fix,
            "confidence_score": float(confidence),
            "agent_name": agent_name,
            "category": finding.get("category") or finding.get("type") or agent_name,
            "title": finding.get("title"),
        }

    def _build_comments(self, result: dict) -> list[PRReviewComment]:
        review_id = UUID(result["review_id"])
        comments: list[PRReviewComment] = []
        seen: set[tuple[str, int, str]] = set()

        for agent_name, _ in AGENT_NODES.items():
            agent_result = result.get(f"{agent_name}_result")
            if not agent_result:
                continue
            for finding in agent_result.get("findings", []):
                normalized = self._normalize_finding(finding, agent_name)
                if not normalized:
                    continue
                key = (
                    normalized["file_path"],
                    normalized["line_number"],
                    normalized["title"] or normalized["explanation"][:80],
                )
                if key in seen:
                    continue
                seen.add(key)
                comments.append(
                    PRReviewComment(
                        review_id=review_id,
                        file_path=normalized["file_path"],
                        line_number=normalized["line_number"],
                        severity=normalized["severity"],
                        explanation=normalized["explanation"],
                        suggested_fix=normalized["suggested_fix"],
                        confidence_score=normalized["confidence_score"],
                        agent_name=normalized["agent_name"],
                        category=normalized["category"],
                        title=normalized["title"],
                    )
                )

        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        comments.sort(
            key=lambda c: (
                severity_rank.get(c.severity, 5),
                -c.confidence_score,
                c.file_path,
                c.line_number,
            )
        )
        return comments

    async def _persist_agent_logs(self, review_id: UUID, result: dict) -> None:
        for agent_name in result.get("agents_to_run", []):
            if agent_name in ("summary", "planner", "progress"):
                continue
            agent_result = result.get(f"{agent_name}_result")
            if not agent_result:
                continue
            log = AgentLog(
                review_id=review_id,
                agent_name=agent_name,
                status="completed",
                output=agent_result,
                findings=agent_result.get("findings"),
                score=agent_result.get("score") or agent_result.get("performance_score"),
                tokens_used=agent_result.get("tokens_used", 0),
                duration_ms=agent_result.get("duration_ms"),
            )
            self.db.add(log)
