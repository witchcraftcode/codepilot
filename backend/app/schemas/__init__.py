"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class ReviewType(str, Enum):
    FULL = "full"
    SECURITY = "security"
    PERFORMANCE = "performance"
    TESTING = "testing"
    DOCUMENTATION = "documentation"
    ARCHITECTURE = "architecture"
    STYLE = "style"
    DEPENDENCIES = "dependencies"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RepositoryStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"


# --- Auth ---


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str | None = None
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


# --- Repository ---


class RepositoryCreate(BaseModel):
    github_url: HttpUrl
    branch: str | None = None


class RepositoryEmbedRequest(BaseModel):
    repository_id: UUID
    branch: str | None = None


class RepositoryEmbedResponse(BaseModel):
    repository_id: UUID
    files_indexed: int
    files_skipped: int
    vectors_indexed: int


class RepositoryResponse(BaseModel):
    id: UUID
    github_url: str
    name: str
    full_name: str
    status: RepositoryStatus
    languages: dict | None = None
    frameworks: list | None = None
    file_count: int
    chunk_count: int
    health_score: int | None = None
    overview: str | None = None
    created_at: datetime
    indexed_at: datetime | None = None

    model_config = {"from_attributes": True}


class RepositoryListResponse(BaseModel):
    repositories: list[RepositoryResponse]
    total: int


# --- Review ---


class ReviewCreate(BaseModel):
    repository_id: UUID
    review_type: ReviewType = ReviewType.FULL
    focus_areas: list[str] | None = None
    custom_prompt: str | None = None


class FindingResponse(BaseModel):
    id: str
    severity: str
    category: str
    title: str
    description: str
    file_path: str | None = None
    line_number: int | None = None
    suggestion: str | None = None


class AgentResultResponse(BaseModel):
    agent_name: str
    score: int | None = None
    findings: list[FindingResponse] = []
    summary: str | None = None
    duration_ms: int | None = None


class ReviewResponse(BaseModel):
    id: UUID
    repository_id: UUID
    review_type: ReviewType
    status: ReviewStatus
    overall_score: int | None = None
    agents_executed: list[str] | None = None
    summary: str | None = None
    top_issues: list[dict] | None = None
    priority_fixes: list[dict] | None = None
    tokens_used: int = 0
    duration_ms: int | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class ReviewDetailResponse(ReviewResponse):
    agent_results: list[AgentResultResponse] = []
    report: dict | None = None


class ReviewListResponse(BaseModel):
    reviews: list[ReviewResponse]
    total: int


# --- Chat ---


class ChatRequest(BaseModel):
    repository_id: UUID
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class ChatSource(BaseModel):
    file_path: str
    chunk_type: str
    symbol_name: str | None = None
    relevance_score: float


class ChatResponse(BaseModel):
    conversation_id: UUID
    message: str
    sources: list[ChatSource] = []


class ChatContextRequest(BaseModel):
    repository_id: UUID
    question: str = Field(..., min_length=1)
    k: int | None = 5
    chunk_types: list[str] | None = None
    language: str | None = None


class RetrievedChunk(BaseModel):
    file_path: str | None = None
    chunk_type: str | None = None
    language: str | None = None
    symbol_name: str | None = None
    content: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    score: float | None = None


class ChatContextResponse(BaseModel):
    repository_id: UUID
    question: str
    retrieved: list[RetrievedChunk]
    latency_ms: int


# --- Specialized endpoints ---


class SecurityAuditRequest(BaseModel):
    repository_id: UUID


class TestGenerationRequest(BaseModel):
    repository_id: UUID
    file_path: str
    function_name: str | None = None
    framework: str | None = None


class DocumentationRequest(BaseModel):
    repository_id: UUID
    target: str = "readme"  # readme, api, function
    file_path: str | None = None


class ExplainFunctionRequest(BaseModel):
    repository_id: UUID
    file_path: str
    function_name: str


class PRReviewRequest(BaseModel):
    repository_id: UUID
    pr_diff: str
    pr_title: str | None = None
    pr_description: str | None = None


class FeedbackCreate(BaseModel):
    review_id: UUID
    finding_id: str
    agent_name: str
    accepted: bool
    comment: str | None = None


# --- Scores ---


class HealthScoreBreakdown(BaseModel):
    security: int
    performance: int
    architecture: int
    documentation: int
    testing: int
    maintainability: int
    overall: int


class ScoresResponse(BaseModel):
    repository_id: UUID
    health_score: HealthScoreBreakdown
    last_review_at: datetime | None = None
    trend: list[dict] | None = None
