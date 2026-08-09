"""Tests for pull request planner configuration."""

from agents.planner import REVIEW_TYPE_AGENTS, plan_agents


class TestPullRequestPlanner:
    def test_pull_request_review_type_exists(self):
        assert "pull_request" in REVIEW_TYPE_AGENTS

    def test_pull_request_runs_security_and_style(self):
        agents = plan_agents("pull_request")
        assert "security" in agents
        assert "performance" in agents
        assert "testing" in agents
        assert "style" in agents
        assert "summary" in agents
        assert "repository" not in agents

    def test_pull_request_does_not_run_documentation(self):
        agents = plan_agents("pull_request")
        assert "documentation" not in agents
