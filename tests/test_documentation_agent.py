import asyncio

from agents.specialized import DocumentationAgent


class TestDocumentationAgent:
    def test_run_generates_readme_and_docstrings(self, monkeypatch):
        agent = DocumentationAgent()
        chunks = [
            {
                "file_path": "src/app.py",
                "language": "python",
                "chunk_type": "function",
                "symbol_name": "process_data",
                "content": "def process_data(data):\n    return [d*2 for d in data]\n",
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

        monkeypatch.setattr(DocumentationAgent, "retrieve_context", fake_retrieve_context)

        async def _run():
            result = await agent.run({"repository_id": "repo-1", "repo_metadata": {"languages": {"python": 2}}})
            assert result["agent_name"] == "documentation"
            assert "generated_artifacts" in result
            assert any(a["type"] == "readme" for a in result["generated_artifacts"])
            assert any(a["type"] == "docstring" for a in result["generated_artifacts"])
            assert result["score"] < 100

        asyncio.run(_run())
