from types import SimpleNamespace

import pytest

from agents import base as base_module
from agents.base import BaseAgent


class ValidationAgent(BaseAgent):
    name = "validation"

    def get_system_prompt(self):
        return "Analyze code."

    async def retrieve_context(self, state):
        return []


class FakeLLM:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return SimpleNamespace(content=self.content)


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(base_module, "VectorStore", lambda: object())
    return ValidationAgent()


@pytest.mark.asyncio
async def test_agent_rejects_empty_or_malformed_model_output(agent):
    agent._llm = FakeLLM("{}")
    with pytest.raises(RuntimeError, match="incomplete analysis"):
        await agent.run({"repository_id": "repo", "repo_metadata": {}})

    agent._llm = FakeLLM("not json")
    with pytest.raises(RuntimeError, match="invalid analysis JSON"):
        await agent.run({"repository_id": "repo", "repo_metadata": {}})


@pytest.mark.asyncio
async def test_agent_does_not_replace_llm_initialization_failure_with_dummy(agent, monkeypatch):
    def fail_provider_init():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(base_module, "get_llm", fail_provider_init)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await agent._ensure_llm()
