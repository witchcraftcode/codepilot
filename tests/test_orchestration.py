"""Tests for LangGraph orchestration logic."""

import pytest

from agents.planner import plan_agents


class TestPlannerAgent:
    def test_full_review_runs_all_agents(self):
        agents = plan_agents("full")
        assert "repository" in agents
        assert "security" in agents
        assert "architecture" in agents
        assert "summary" in agents

    def test_security_review_runs_subset(self):
        agents = plan_agents("security")
        assert "security" in agents
        assert "dependencies" in agents
        assert "architecture" not in agents
        assert "summary" in agents

    def test_performance_review(self):
        agents = plan_agents("performance")
        assert "performance" in agents
        assert "architecture" in agents
        assert "testing" not in agents

    def test_focus_areas_filter(self):
        agents = plan_agents("full", focus_areas=["security", "testing"])
        assert "security" in agents
        assert "testing" in agents
        assert "architecture" not in agents


class TestCodeChunker:
    def test_python_function_chunking(self):
        from parsers.chunker import CodeChunker

        chunker = CodeChunker()
        code = '''
def hello():
    return "world"

class MyClass:
    def method(self):
        pass
'''
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "test.py"
            f.write_text(code)
            chunks = chunker.chunk_file(f, "test.py", "python")

        types = [c.chunk_type for c in chunks]
        assert "file" in types
        assert "function" in types
        assert "class" in types
        assert "method" in types

    def test_javascript_chunking(self):
        from parsers.chunker import CodeChunker

        chunker = CodeChunker()
        code = '''
export function fetchData() {
    return fetch("/api");
}

export class DataService {
    async getData() {
        return [];
    }
}
'''
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "app.js"
            f.write_text(code)
            chunks = chunker.chunk_file(f, "app.js", "javascript")

        assert len(chunks) >= 2
        symbol_names = [c.symbol_name for c in chunks if c.symbol_name]
        assert "fetchData" in symbol_names or "DataService" in symbol_names


class TestLanguageUtils:
    def test_detect_language(self):
        from parsers.language_utils import detect_language

        assert detect_language("app.py") == "python"
        assert detect_language("index.ts") == "typescript"
        assert detect_language("Main.java") == "java"
        assert detect_language("main.go") == "go"
        assert detect_language("readme.md") is None

    def test_should_ignore(self):
        from pathlib import Path
        from parsers.language_utils import should_ignore_path

        assert should_ignore_path(Path("node_modules/package/index.js"))
        assert should_ignore_path(Path(".git/config"))
        assert not should_ignore_path(Path("src/main.py"))


class TestRetrievalMetrics:
    def test_precision_at_k(self):
        from evaluation.ragas_eval import compute_precision_at_k

        relevant = {"a.py", "b.py"}
        retrieved = ["a.py", "c.py", "b.py", "d.py", "e.py"]
        assert compute_precision_at_k(relevant, retrieved, k=5) == 0.4

    def test_recall_at_k(self):
        from evaluation.ragas_eval import compute_recall_at_k

        relevant = {"a.py", "b.py"}
        retrieved = ["a.py", "c.py", "x.py"]
        assert compute_recall_at_k(relevant, retrieved, k=3) == 0.5

    def test_mrr(self):
        from evaluation.ragas_eval import compute_mrr

        relevant = {"b.py"}
        retrieved = ["a.py", "b.py", "c.py"]
        assert compute_mrr(relevant, retrieved) == 0.5


class TestGitHubURLParser:
    def test_parse_url(self):
        from parsers.repository_loader import RepositoryLoader

        loader = RepositoryLoader()
        owner, repo = loader.parse_github_url("https://github.com/fastapi/fastapi")
        assert owner == "fastapi"
        assert repo == "fastapi"

        owner, repo = loader.parse_github_url("https://github.com/owner/repo.git")
        assert owner == "owner"
        assert repo == "repo"

    def test_invalid_url(self):
        from parsers.repository_loader import RepositoryLoader

        loader = RepositoryLoader()
        with pytest.raises(ValueError):
            loader.parse_github_url("https://gitlab.com/user/repo")
