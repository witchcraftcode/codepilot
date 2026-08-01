import asyncio

from agents.specialized import TestingAgent as TestingAgentClass


class TestTestingAgent:
    def test_run_suggests_tests_for_functions_and_endpoints(self, monkeypatch):
        agent = TestingAgentClass()
        chunks = [
            {
                "file_path": "src/service.py",
                "language": "python",
                "chunk_type": "function",
                "symbol_name": "process_item",
                "content": "def process_item(item):\n    return item * 2\n",
                "start_line": 1,
            },
            {
                "file_path": "src/api.py",
                "language": "python",
                "chunk_type": "function",
                "symbol_name": "create_item",
                "content": "@app.route('/items')\ndef create_item():\n    return {}\n",
                "start_line": 1,
            },
        ]

        async def fake_retrieve_context(self, state):
            return chunks

        monkeypatch.setattr(TestingAgentClass, "retrieve_context", fake_retrieve_context)

        async def _run():
            result = await agent.run({"repository_id": "repo-1", "repo_metadata": {"languages": {"python": 2}}})
            assert result["agent_name"] == "testing"
            assert "generated_artifacts" in result
            assert any(a["type"] == "unit_test" for a in result["generated_artifacts"])
            assert any(a["type"] == "integration_test" for a in result["generated_artifacts"])
            assert any(a["type"] == "test_plan" or a["path"] == "tests/README.md" for a in result["generated_artifacts"])
            assert result["score"] < 100
            assert len(result["findings"]) >= 2

        asyncio.run(_run())
