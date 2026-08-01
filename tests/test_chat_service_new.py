import asyncio

from app.services.chat_service import ChatService


class FakeRepo:
    def __init__(self):
        self.status = "ready"
        self.full_name = "owner/repo"


class FakeDB:
    def __init__(self):
        self._conv = None

    async def execute(self, arg):
        # For repository check
        class Res:
            def __init__(self, obj):
                self._obj = obj

            def scalar_one_or_none(self):
                return self._obj

        if arg == "repo-1":
            return Res(FakeRepo())
        # conversation select
        return Res(None)

    def add(self, obj):
        self._conv = obj

    async def flush(self):
        return


class DummyLLM:
    async def ainvoke(self, messages):
        class R:
            def __init__(self):
                self.content = "The function add in file.py adds numbers. [file.py:1-3:add]"
                self.token_usage = 10

        return R()


class DummyHybrid:
    async def retrieve(self, repository_id, query, top_k=5):
        return {
            "results": [
                {"content": "def add(a,b): return a+b", "file_path": "file.py", "symbol_name": "add", "start_line": 1, "end_line": 3, "sha256": "h1", "semantic_score": 0.9}
            ],
            "metrics": {"semantic_latency_ms": 10, "keyword_latency_ms": 5, "rerank_latency_ms": 2, "overall_latency_ms": 20},
        }


async def run_chat():
    db = FakeDB()
    service = ChatService(db)
    # override components
    service.get_llm = lambda **kwargs: DummyLLM()
    service.llm = service.get_llm()
    service.vector_store = None
    # monkeypatch hybrid retriever used in chat
    from app.services.hybrid_retrieval import HybridRetrievalService

    async def fake_retrieve(self, repository_id, query, top_k=5):
        return await DummyHybrid().retrieve(repository_id, query, top_k=top_k)

    # patch at runtime on the class so instances use it
    from app import services
    services.hybrid_retrieval.HybridRetrievalService.retrieve = fake_retrieve  # type: ignore

    res = await service.chat("repo-1", "user-1", "What does add do?", None, top_k=1)
    assert "add" in res["message"]
    assert res["sources"]
    assert "llm_latency_ms" in res["metrics"]


def test_chat():
    asyncio.run(run_chat())
