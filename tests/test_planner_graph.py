import asyncio
import pytest

from graph.workflow import ReviewWorkflow
from graph.state import ReviewState


def test_planner_dynamic_routing(monkeypatch):
    async def _run():
        # Patch PlannerAgent.plan to return a targeted plan
        async def fake_plan(self, state):
            return {"agents": [{"name": "repository", "priority": 100}, {"name": "security", "priority": 90}, {"name": "summary", "priority": 10}], "summary": "Run repository then security"}

        import agents.specialized as spec

        monkeypatch.setattr(spec.PlannerAgent, "plan", fake_plan)

        # Patch agent run methods to return predictable results
        async def fake_run_repo(self, state):
            return {
                "agent_name": "repository",
                "score": 80,
                "findings": [],
                "summary": "Repo ok",
                "tokens_used": 10,
                "duration_ms": 10,
            }

        async def fake_run_sec(self, state):
            return {
                "agent_name": "security",
                "score": 60,
                "findings": [],
                "summary": "No critical issues",
                "tokens_used": 20,
                "duration_ms": 20,
            }

        async def fake_summarize(self, state, results):
            return {"overall_score": 70, "summary": "Combined", "top_issues": [], "priority_fixes": [], "roadmap": []}

        monkeypatch.setattr(spec.RepositoryAgent, "run", fake_run_repo)
        monkeypatch.setattr(spec.SecurityAgent, "run", fake_run_sec)
        monkeypatch.setattr(spec.SummaryAgent, "summarize", fake_summarize)

        # Build workflow and run
        wf = ReviewWorkflow()
        initial: ReviewState = {
            "repository_id": "repo-1",
            "review_id": "r1",
            "review_type": "security",
            "user_request": "Find security issues",
            "focus_areas": [],
            "agents_to_run": [],
            "execution_plan": "",
            "repo_metadata": {},
            "retrieved_context": [],
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
            "total_tokens": 0,
            "messages": [],
            "errors": [],
            "progress_updates": [],
        }

        result = await wf.run(initial)

        assert result["repository_result"]["agent_name"] == "repository"
        assert result["security_result"]["agent_name"] == "security"
        assert result["overall_score"] == 70
        assert result["duration_ms"] >= 0

    asyncio.run(_run())


def test_full_review_workflow_progress(monkeypatch):
    async def _run():
        async def fake_plan(self, state):
            return {
                "agents": [
                    {"name": "repository", "priority": 100},
                    {"name": "security", "priority": 90},
                    {"name": "architecture", "priority": 80},
                    {"name": "performance", "priority": 70},
                    {"name": "testing", "priority": 60},
                    {"name": "documentation", "priority": 50},
                    {"name": "dependencies", "priority": 40},
                    {"name": "summary", "priority": 10},
                ],
                "summary": "Run complete workflow",
            }

        import agents.specialized as spec

        monkeypatch.setattr(spec.PlannerAgent, "plan", fake_plan)

        async def fake_generic_run(self, state):
            return {
                "agent_name": self.name,
                "score": 80,
                "findings": [],
                "summary": f"{self.name} complete",
                "tokens_used": 5,
                "duration_ms": 5,
            }

        for agent_cls in [
            spec.RepositoryAgent,
            spec.SecurityAgent,
            spec.ArchitectureAgent,
            spec.PerformanceAgent,
            spec.TestingAgent,
            spec.DocumentationAgent,
            spec.DependencyAgent,
        ]:
            monkeypatch.setattr(agent_cls, "run", fake_generic_run)

        async def fake_summarize(self, state, results):
            return {
                "overall_score": 80,
                "summary": "Executive review summary.",
                "top_issues": [],
                "priority_fixes": [{"title": "Fix issue", "effort": "medium", "impact": "high"}],
                "roadmap": [{"phase": "stabilize", "items": ["Address critical issues"]}],
                "security_score": 80,
                "architecture_score": 80,
                "performance_score": 80,
                "testing_score": 80,
                "documentation_score": 80,
                "dependency_score": 80,
                "estimated_effort": "1-2 weeks",
                "executive_summary": "A complete review was executed successfully.",
            }

        monkeypatch.setattr(spec.SummaryAgent, "summarize", fake_summarize)

        progress_order = []

        async def progress_callback(state, current_stage):
            progress_order.append(current_stage)

        from graph.workflow import ReviewWorkflow

        wf = ReviewWorkflow(progress_callback=progress_callback)
        initial: ReviewState = {
            "repository_id": "repo-1",
            "review_id": "r1",
            "review_type": "full",
            "user_request": "Complete review",
            "focus_areas": [],
            "agents_to_run": [],
            "execution_plan": "",
            "repo_metadata": {},
            "retrieved_context": [],
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
            "total_tokens": 0,
            "messages": [],
            "errors": [],
            "progress_updates": [],
        }

        result = await wf.run(initial)
        assert progress_order[0] == "planner"
        assert progress_order[1:] == [
            "repository",
            "security",
            "architecture",
            "performance",
            "testing",
            "documentation",
            "dependencies",
            "summary",
        ]
        assert result["overall_score"] == 80
        assert result["summary"] == "Executive review summary."
        assert result["priority_fixes"] == [{"title": "Fix issue", "effort": "medium", "impact": "high"}]
        assert result["roadmap"] == [{"phase": "stabilize", "items": ["Address critical issues"]}]
        assert result["security_result"]["agent_name"] == "security"
        assert result["documentation_result"]["agent_name"] == "documentation"

    asyncio.run(_run())
