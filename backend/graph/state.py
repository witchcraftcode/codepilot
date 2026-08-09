"""Shared state for LangGraph multi-agent workflow."""

from typing import Annotated, Any, TypedDict

try:
    from langgraph.graph.message import add_messages
except Exception:
    # Fallback no-op decorator when langgraph is not available in test env
    def add_messages(x):
        return x


class AgentFinding(TypedDict):
    id: str
    severity: str
    category: str
    title: str
    description: str
    file_path: str | None
    line_number: int | None
    suggestion: str | None


class AgentResult(TypedDict):
    agent_name: str
    score: int | None
    findings: list[AgentFinding]
    summary: str
    tokens_used: int
    duration_ms: int


class ReviewState(TypedDict):
    repository_id: str
    review_id: str
    review_type: str
    user_request: str
    focus_areas: list[str]

    # Planner output
    agents_to_run: list[str]
    execution_plan: str

    # Repository context
    repo_metadata: dict[str, Any]
    retrieved_context: list[dict[str, Any]]

    # Agent results
    repository_result: AgentResult | None
    architecture_result: AgentResult | None
    security_result: AgentResult | None
    performance_result: AgentResult | None
    testing_result: AgentResult | None
    documentation_result: AgentResult | None
    style_result: AgentResult | None
    dependency_result: AgentResult | None

    # Summary
    overall_score: int | None
    summary: str | None
    top_issues: list[dict[str, Any]]
    priority_fixes: list[dict[str, Any]]
    roadmap: list[dict[str, Any]]

    # Progress and metrics
    progress_updates: list[dict[str, Any]]
    total_tokens: int
    messages: Annotated[list, add_messages]
    errors: list[str]
