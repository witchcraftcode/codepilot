import asyncio

import pytest

from agents.specialized import SecurityAgent


class TestSecurityAgent:
    def test_find_hardcoded_secret(self):
        agent = SecurityAgent()
        content = 'API_KEY = "abcd1234"\npassword: "secret"\n'
        findings = agent._analyze_chunk(content, "app.py", 1, "python")

        assert any(f["title"] == "Hardcoded secret detected" for f in findings)
        assert any(f["severity"] == "critical" for f in findings)
        assert all(f["file_path"] == "app.py" for f in findings)

    def test_find_sql_injection(self):
        agent = SecurityAgent()
        content = 'cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)\n'
        findings = agent._analyze_chunk(content, "db.py", 1, "python")

        assert any(f["title"] == "Potential SQL injection" for f in findings)
        assert any(f["severity"] == "critical" for f in findings)
        assert findings[0]["line_number"] == 1

    def test_find_command_injection(self):
        agent = SecurityAgent()
        content = 'subprocess.run("rm -rf " + user_input, shell=True)\n'
        findings = agent._analyze_chunk(content, "cli.py", 1, "python")

        assert any(f["title"] == "Potential command injection" for f in findings)
        assert any(f["severity"] == "critical" for f in findings)

    def test_find_prompt_injection(self):
        agent = SecurityAgent()
        content = 'prompt = "Hello " + user_text\n'
        findings = agent._analyze_chunk(content, "bot.py", 1, "python")

        assert any(f["title"] == "Potential prompt injection" for f in findings)
        assert any(f["severity"] == "high" for f in findings)

    def test_run_uses_retrieved_context(self, monkeypatch):
        agent = SecurityAgent()
        context_chunks = [
            {
                "file_path": "auth.py",
                "language": "python",
                "content": "jwt.decode(token, secret)\n",
                "start_line": 10,
            }
        ]

        async def fake_retrieve_context(self, state):
            return context_chunks

        monkeypatch.setattr(SecurityAgent, "retrieve_context", fake_retrieve_context)

        async def _run():
            result = await agent.run({"repository_id": "repo-1", "user_request": "Find security issues"})
            assert result["agent_name"] == "security"
            assert result["score"] < 100
            assert result["findings"]
            assert any(f["title"] == "Missing JWT algorithm validation" or f["title"] == "Insecure JWT validation" for f in result["findings"])

        asyncio.run(_run())
