"""Simplified LangGraph workflow with conditional agent routing."""

import time
from typing import Any

try:
    from langgraph.graph import END, StateGraph
except Exception:
    # Minimal fallback for environments without langgraph (tests)
    END = "END"

    class StateGraph:
        def __init__(self, state_type=None):
            self.nodes = {}
            self.entry = None
            self.edges = {}
            self.cond_funcs = {}

        def add_node(self, name, fn):
            self.nodes[name] = fn

        def set_entry_point(self, name):
            self.entry = name

        def add_edge(self, a, b):
            self.edges.setdefault(a, []).append(b)

        def add_conditional_edges(self, name, route_fn):
            self.cond_funcs[name] = route_fn

        def compile(self, progress_callback=None):
            # return an object with ainvoke that sequentially calls nodes based on cond funcs
            graph = self

            class Compiled:
                async def ainvoke(self, state):
                    current = graph.entry
                    while current and current != END:
                        fn = graph.nodes.get(current)
                        if fn:
                            out = await fn(state)
                            if out:
                                state.update(out)
                        if progress_callback:
                            if callable(progress_callback):
                                maybe_coro = progress_callback(state, current)
                                if hasattr(maybe_coro, "__await__"):
                                    await maybe_coro
                        # routing
                        if current in graph.cond_funcs:
                            current = graph.cond_funcs[current](state)
                        else:
                            # next edge or end
                            nexts = graph.edges.get(current, [])
                            current = nexts[0] if nexts else END
                    return state

            return Compiled()

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

try:
    from app.services.observability import record_agent_execution, trace_span
except Exception:  # pragma: no cover - graph tests can run without full app deps
    def record_agent_execution(node: str, duration_ms: float) -> None:
        return None

    from contextlib import contextmanager

    @contextmanager
    def trace_span(name: str, **attributes):
        yield None

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
    "security",
    "architecture",
    "performance",
    "testing",
    "documentation",
    "dependencies",
    "style",
    "summary",
]


async def planner_node(state: ReviewState) -> dict[str, Any]:
    start = time.perf_counter()
    planner = PlannerAgent()
    with trace_span("langgraph.node", node="planner"):
        try:
            plan = await planner.plan(state)
        finally:
            record_agent_execution("planner", int((time.perf_counter() - start) * 1000))

    # plan may be dict or list
    if isinstance(plan, dict):
        agents = [a["name"] for a in plan.get("agents", [])]
        return {
            "agents_to_run": agents,
            "execution_plan": plan.get("summary") or f"Executing: {', '.join(agents)}",
            "plan_details": plan,
        }
    else:
        agents = list(plan)
        return {"agents_to_run": agents, "execution_plan": f"Executing: {', '.join(agents)}"}


def make_agent_node(agent_name: str):
    async def node(state: ReviewState) -> dict[str, Any]:
        start = time.perf_counter()
        with trace_span("langgraph.node", node=agent_name):
            try:
                if agent_name not in state.get("agents_to_run", []):
                    return {}
                agent_cls, result_key = AGENT_NODES[agent_name]
                agent = agent_cls()
                result = await agent.run(state)
                return {
                    result_key: result,
                    "total_tokens": state.get("total_tokens", 0) + result["tokens_used"],
                }
            finally:
                record_agent_execution(agent_name, int((time.perf_counter() - start) * 1000))

    return node


async def summary_node(state: ReviewState) -> dict[str, Any]:
    start = time.perf_counter()
    with trace_span("langgraph.node", node="summary"):
        try:
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
        finally:
            record_agent_execution("summary", int((time.perf_counter() - start) * 1000))


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
    def __init__(self, progress_callback=None) -> None:
        self.graph = build_review_graph().compile(progress_callback)

    async def run(self, initial_state: ReviewState) -> ReviewState:
        start = time.time()
        result = await self.graph.ainvoke(initial_state)
        result["duration_ms"] = int((time.time() - start) * 1000)
        return result
