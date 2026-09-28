from typing import List

from graph.state import ReviewState
from graph.workflow import ReviewWorkflow

from app.services.pr_context_service import PRContextService

from .schemas import ChangedFile, ReviewComment


class PullRequestReviewOrchestrator:
    def __init__(self):
        self.workflow = ReviewWorkflow()
        self.context_service = PRContextService()

    async def review(
        self,
        repository_id: str,
        owner: str,
        repo: str,
        pr_number: int,
        files: List[ChangedFile],
    ) -> List[ReviewComment]:

        comments: List[ReviewComment] = []

        for file in files:

            # Skip binary files
            if not file.patch:
                continue

            # Retrieve semantic repository context
            context = await self.context_service.retrieve(
                repository_id=repository_id,
                filename=file.filename,
                patch=file.patch,
            )

            state: ReviewState = {
                # PR context
                "pr_mode": True,
                "pr_owner": owner,
                "pr_repo": repo,
                "pr_number": pr_number,
                "changed_files": [],
                "current_file": {
                    "filename": file.filename,
                    "patch": file.patch,
                    "status": file.status,
                },

                # Existing workflow fields
                "repository_id": repository_id,
                "review_id": "",
                "review_type": "pull_request",
                "user_request": "Review this pull request",
                "focus_areas": [],
                "agents_to_run": [],
                "execution_plan": "",
                "repo_metadata": {},
                "retrieved_context": context,
                "repository_result": None,
                "architecture_result": None,
                "security_result": None,
                "performance_result": None,
                "testing_result": None,
                "documentation_result": None,
                "style_result": None,
                "dependency_result": None,
                "overall_score": None,
                "summary": None,
                "top_issues": [],
                "priority_fixes": [],
                "roadmap": [],
                "progress_updates": [],
                "total_tokens": 0,
                "messages": [],
                "errors": [],
            }

            result = await self.workflow.run(state)

            # Collect findings from every executed agent
            for key in [
                "security_result",
                "architecture_result",
                "performance_result",
                "testing_result",
                "documentation_result",
                "style_result",
            ]:
                agent = result.get(key)

                if not agent:
                    continue

                for finding in agent.get("findings", []):
                    comments.append(
                        ReviewComment(
                            file=file.filename,
                            line=finding.get("line_number", 1),
                            severity=finding["severity"],
                            category=finding["category"],
                            message=finding["description"],
                            suggestion=finding.get("suggestion", ""),
                            confidence=0.90,
                        )
                    )

        return comments