from fastapi import APIRouter, HTTPException

from .comment_mapper import GitHubCommentMapper

from .schemas import (
    PullRequestReviewRequest,
    PullRequestReviewResponse,
)
from .services import GitHubService
from .review_orchestrator import PullRequestReviewOrchestrator

router = APIRouter(prefix="/github", tags=["GitHub"])


@router.post(
    "/pull-request",
    response_model=PullRequestReviewResponse,
)
async def review_pull_request(request: PullRequestReviewRequest):

    github = GitHubService(token=request.github_token)

    try:
        pr = await github.get_pull_request(
            request.owner,
            request.repo,
            request.pull_number,
        )

        files = await github.get_changed_files(
            request.owner,
            request.repo,
            request.pull_number,
        )

        orchestrator = PullRequestReviewOrchestrator()

        comments = await orchestrator.review(
            repository_id=request.repository_id,
            owner=request.owner,
            repo=request.repo,
            pr_number=request.pull_number,
            files=files,
        )

        # Get latest commit SHA
        head_sha = await github.get_head_commit(
            request.owner,
            request.repo,
            request.pull_number,
        )

        # Convert AI findings into GitHub Review API format
        github_comments = GitHubCommentMapper.to_github(comments)

        # Publish review only if findings exist
        if github_comments:
            await github.create_review(
                owner=request.owner,
                repo=request.repo,
                pr=request.pull_number,
                commit_id=head_sha,
                comments=github_comments,
                body="🤖 CodePilot AI Pull Request Review",
            )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return PullRequestReviewResponse(
        title=pr["title"],
        author=pr["user"]["login"],
        files_changed=len(files),
        comments=comments,
        summary=(
            f"Analyzed {len(files)} changed files and "
            f"generated {len(comments)} review findings."
        ),
    )