import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.repository import Repository
from app.models.user import User
from .comment_mapper import GitHubCommentMapper

from .schemas import (
    PullRequestReviewRequest,
    PullRequestReviewResponse,
)
from .services import GitHubService
from .review_orchestrator import PullRequestReviewOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/github", tags=["GitHub"])


@router.post(
    "/pull-request",
    response_model=PullRequestReviewResponse,
)
async def review_pull_request(
    request: PullRequestReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repository_result = await db.execute(
        select(Repository).where(
            Repository.id == request.repository_id,
            Repository.owner_id == user.id,
        )
    )
    repository = repository_result.scalar_one_or_none()
    if repository is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    requested_name = f"{request.owner}/{request.repo}".casefold()
    if (repository.full_name or "").casefold() != requested_name:
        raise HTTPException(
            status_code=403,
            detail="Pull request repository does not match the indexed repository",
        )
    if not user.access_token:
        raise HTTPException(
            status_code=403,
            detail="Connect a GitHub account with pull-request write access",
        )

    # The legacy github_token body field remains accepted for compatibility,
    # but is deliberately ignored. Credentials come from the authenticated user.
    github = GitHubService(token=user.access_token)

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

        if not isinstance(pr, dict) or not isinstance(pr.get("user"), dict):
            raise ValueError("Malformed pull request response")
        head = pr.get("head")
        if not pr.get("title") or not pr["user"].get("login"):
            raise ValueError("Malformed pull request response")
        if not isinstance(head, dict) or not isinstance(head.get("sha"), str):
            raise ValueError("Malformed pull request response")

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

    except httpx.HTTPStatusError as exc:
        upstream_status = exc.response.status_code
        if upstream_status in (403, 404, 429):
            raise HTTPException(
                status_code=upstream_status,
                detail="GitHub rejected the pull-request operation; verify repository access and permissions",
            ) from exc
        logger.warning("GitHub pull-request review failed with upstream status %s", upstream_status)
        raise HTTPException(status_code=502, detail="GitHub pull-request service failed") from exc
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        logger.warning("GitHub pull-request review could not reach GitHub")
        raise HTTPException(status_code=502, detail="GitHub pull-request service is unavailable") from exc
    except ValueError as exc:
        logger.warning("GitHub returned an invalid pull-request response")
        raise HTTPException(status_code=502, detail="GitHub returned an invalid response") from exc

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
