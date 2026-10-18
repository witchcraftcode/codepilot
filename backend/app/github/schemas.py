from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PullRequestReviewRequest(BaseModel):
    repository_id: UUID

    owner: str = Field(..., pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", examples=["openai"])
    repo: str = Field(..., pattern=r"^[A-Za-z0-9._-]{1,100}$", examples=["openai-python"])

    pull_number: int = Field(..., ge=1)

    github_token: Optional[str] = Field(
        default=None,
        repr=False,
        description="Deprecated and ignored. Authenticate with a CodePilot bearer token; the connected GitHub account is used.",
    )


class ChangedFile(BaseModel):
    filename: str
    status: str

    additions: int
    deletions: int
    changes: int

    patch: Optional[str] = None


class ReviewComment(BaseModel):
    file: str
    line: int

    severity: str
    category: str

    message: str
    suggestion: str

    confidence: float


class PullRequestReviewResponse(BaseModel):
    title: str
    author: str

    files_changed: int

    comments: List[ReviewComment]

    summary: str
