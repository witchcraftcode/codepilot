import asyncio

from agents.specialized import PerformanceAgent


class TestPerformanceAgent:
    def test_detect_n_plus_one(self):
        agent = PerformanceAgent()
        content = """
for item in items:
    cursor.execute("SELECT * FROM table WHERE id = %s" % item.id)
"""
        finds = agent._analyze_performance_chunk(content, "db.py", "python")
        assert any(f["title"] == "Possible N+1 database queries" for f in finds)

    def test_detect_blocking_io_in_async(self):
        agent = PerformanceAgent()
        content = """
async def handler(req):
    import requests
    r = requests.get('http://example.com')
    return r.text
"""
        finds = agent._analyze_performance_chunk(content, "srv.py", "python")
        assert any(f["title"] == "Blocking I/O in async context" for f in finds)

    def test_detect_redundant_allocations(self):
        agent = PerformanceAgent()
        content = """
for x in items:
    a = []
    a.append(x)
"""
        finds = agent._analyze_performance_chunk(content, "loop.py", "python")
        assert any(f["title"] == "Redundant allocations in loop" for f in finds)

    def test_detect_recursive_bottleneck(self):
        agent = PerformanceAgent()
        content = """
def fib(n):
    if n < 2:
        return n
    return fib(n-1) + fib(n-2)
"""
        finds = agent._analyze_performance_chunk(content, "alg.py", "python")
        assert any(f["title"] == "Recursive function without memoization" for f in finds)

    def test_run_returns_metrics(self, monkeypatch):
        agent = PerformanceAgent()
        chunks = [
            {"file_path": "srv.py", "language": "python", "content": "async def h():\n    import requests\n    r = requests.get('x')\n", "start_line": 1},
        ]

        async def fake_retrieve_context(self, state):
            return chunks

        monkeypatch.setattr(PerformanceAgent, "retrieve_context", fake_retrieve_context)

        async def _run():
            res = await agent.run({"repository_id": "repo-1"})
            assert res["agent_name"] == "performance"
            assert "performance_metrics" in res
            assert "findings" in res

        asyncio.run(_run())
