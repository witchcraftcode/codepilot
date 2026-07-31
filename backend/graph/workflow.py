"""Simplified LangGraph workflow with conditional agent routing."""

import time
from typing import Any

from langgraph.graph import END, StateGraph

from agents.specialized import (
    ArchitectureAgent,
    DependencyAgent,
    DocumentationAgent,
    PerformanceAgent,
    PlannerAgent,
    RepositoryAgent,
    SecurityAgent,
    StyleAgent,
    SummaryAgent,
    TestingAgent,
)
from graph.state import ReviewState

AGENT_NODES = {
    "repository": (RepositoryAgent, "repository_result"),
    "architecture": (ArchitectureAgent, "architecture_result"),
    "security": (SecurityAgent, "security_result"),
    "performance": (PerformanceAgent, "performance_result"),
    "testing": (TestingAgent, "testing_result"),
    "documentation": (DocumentationAgent, "documentation_result"),
    "style": (StyleAgent, "style_result"),
    "dependencies": (DependencyAgent, "dependency_result"),
}

EXECUTION_ORDER = [
    "repository",
    "architecture",
    "security",
    "performance",
    "testing",
    "documentation",
    "style",
    "dependencies",
    "summary",
]


async def planner_node(state: ReviewState) -> dict[str, Any]:
    planner = PlannerAgent()
    agents = await planner.plan(state)
    return {
        "agents_to_run": agents,
        "execution_plan": f"Executing: {', '.join(agents)}",
    }


def make_agent_node(agent_name: str):
    async def node(state: ReviewState) -> dict[str, Any]:
        if agent_name not in state.get("agents_to_run", []):
            return {}
        agent_cls, result_key = AGENT_NODES[agent_name]
        agent = agent_cls()
        result = await agent.run(state)
        return {
            result_key: result,
            "total_tokens": state.get("total_tokens", 0) + result["tokens_used"],
        }

    return node


async def summary_node(state: ReviewState) -> dict[str, Any]:
    if "summary" not in state.get("agents_to_run", []):
        return {}
    summary_agent = SummaryAgent()
    agent_results = []
    for name, (_, result_key) in AGENT_NODES.items():
        result = state.get(result_key)
        if result:
            agent_results.append(result)

    summary = await summary_agent.summarize(state, agent_results)
    return {
        "overall_score": summary.get("overall_score"),
        "summary": summary.get("summary"),
        "top_issues": summary.get("top_issues", []),
        "priority_fixes": summary.get("priority_fixes", []),
        "roadmap": summary.get("roadmap", []),
    }


def route_next(current: str):
    def router(state: ReviewState) -> str:
        agents = state.get("agents_to_run", EXECUTION_ORDER)
        try:
            idx = EXECUTION_ORDER.index(current)
        except ValueError:
            return END
        for next_agent in EXECUTION_ORDER[idx + 1 :]:
            if next_agent in agents:
                return next_agent
        return END

    return router


def build_review_graph() -> StateGraph:
    graph = StateGraph(ReviewState)

    graph.add_node("planner", planner_node)
    graph.add_node("summary", summary_node)

    for name in AGENT_NODES:
        graph.add_node(name, make_agent_node(name))

    graph.set_entry_point("planner")
    graph.add_edge("planner", "repository")

    for i, agent in enumerate(EXECUTION_ORDER[:-1]):
        next_agent = EXECUTION_ORDER[i + 1]
        graph.add_conditional_edges(agent, route_next(agent))

    graph.add_edge("summary", END)

    return graph


class ReviewWorkflow:
    def __init__(self) -> None:
        self.graph = build_review_graph().compile()

    async def run(self, initial_state: ReviewState) -> ReviewState:
        start = time.time()
        result = await self.graph.ainvoke(initial_state)
        result["duration_ms"] = int((time.time() - start) * 1000)
        return result
