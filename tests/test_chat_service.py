import asyncio
from uuid import uuid4

from app.services.chat_service import ChatService


class DummyResult:
    def __init__(self, value):
        self.content = value


class FakeDBExecuteResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeRepo:
    def __init__(self):
        self.full_name = "owner/repo"
        self.status = "ready"


class FakeDB:
    def __init__(self, repo):
        self.repo = repo

    async def execute(self, *args, **kwargs):
        return FakeDBExecuteResult(self.repo)

    def add(self, obj):
        # no-op
        pass

    async def flush(self):
        pass


class FakeLLM:
    async def ainvoke(self, messages):
        # Echo back a safe response that references the provided context
        return DummyResult("Based on the repository code, the function returns True.\n[CITATION] src/app.py:1-2:hello")


class FakeVectorStore:
    async def search(self, query, repository_id, limit=8):
        return [
            {
                "score": 0.98,
                "file_path": "src/app.py",
                "chunk_type": "function",
                "language": "python",
                "symbol_name": "hello",
                "content": "def hello():\n    return True",
                "start_line": 1,
                "end_line": 2,
            }
        ]


def test_chat_service_returns_grounded_answer_and_citations(monkeypatch):
    repo = FakeRepo()
    db = FakeDB(repo)

    # Create ChatService instance without calling __init__
    svc = ChatService.__new__(ChatService)
    svc.db = db
    svc.llm = FakeLLM()
    svc.vector_store = FakeVectorStore()

    out = asyncio.run(svc.chat(uuid4(), uuid4(), "Does it return True?"))

    assert "message" in out
    assert "sources" in out
    assert len(out["sources"]) == 1
    src = out["sources"][0]
    assert src["file_path"] == "src/app.py"
    assert src["symbol"] == "hello"
