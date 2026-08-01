import asyncio

from agents.specialized import ArchitectureAgent


class TestArchitectureAgent:
    def test_detect_large_class_and_function(self):
        agent = ArchitectureAgent()
        # create a file with a large class (many methods) and long function
        class_code = """
class BigService:
    def m1(self):\n        pass\n
"""
        # append many methods
        for i in range(20):
            class_code += f"    def method_{i}(self):\n        pass\n\n"

        func_code = "def huge():\n" + "\n" .join(["    x=1" for _ in range(200)]) + "\n"
        content = class_code + "\n" + func_code

        metrics = agent._analyze_chunk(content, "big.py", "python")
        assert metrics["num_classes"] >= 1
        assert metrics["avg_methods_per_class"] > 12

    def test_detect_cyclic_dependencies(self):
        agent = ArchitectureAgent()
        chunks = [
            {"file_path": "a.py", "content": "import b\nfrom b import something\n"},
            {"file_path": "b.py", "content": "import a\nfrom a import other\n"},
        ]
        cycles = agent._detect_cyclic_dependencies(chunks)
        assert "a.py" in cycles or "b.py" in cycles

    def test_run_returns_structure(self, monkeypatch):
        agent = ArchitectureAgent()
        chunks = [
            {"file_path": "service.py", "language": "python", "content": "def fn():\n    return 1\n", "start_line": 1},
            {"file_path": "model.py", "language": "python", "content": "class Model:\n    pass\n", "start_line": 1},
        ]

        async def fake_retrieve_context(self, state):
            return chunks

        monkeypatch.setattr(ArchitectureAgent, "retrieve_context", fake_retrieve_context)

        async def _run():
            res = await agent.run({"repository_id": "repo-1"})
            assert res["agent_name"] == "architecture"
            assert "architecture_score" in res
            assert "strengths" in res and isinstance(res["strengths"], list)
            assert "weaknesses" in res and isinstance(res["weaknesses"], list)
            assert "improvement_roadmap" in res and isinstance(res["improvement_roadmap"], list)

        asyncio.run(_run())
