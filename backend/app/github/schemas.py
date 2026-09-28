from typing import List, Optional

from pydantic import BaseModel, Field


class PullRequestReviewRequest(BaseModel):
    repository_id: str

    owner: str = Field(..., examples=["openai"])
    repo: str = Field(..., examples=["openai-python"])

    pull_number: int = Field(..., gt=0)

    github_token: Optional[str] = None


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