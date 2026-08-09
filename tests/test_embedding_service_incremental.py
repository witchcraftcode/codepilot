"""Tests for incremental repository indexing."""

import asyncio
import hashlib
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from git import Repo

from app.services.embedding_service import EmbeddingService
from parsers.chunker import CodeChunk


class FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar(self):
        return self._scalar

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self):
        self.added = []
        self.execute_calls = 0
        self.flush_calls = 0

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, query):
        self.execute_calls += 1
        return FakeResult()

    async def flush(self):
        self.flush_calls += 1


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def test_hash_indexable_files_uses_sha256_and_ignores_unsupported_files():
    service = EmbeddingService(FakeDB())
    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        (repo_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (repo_path / "notes.txt").write_text("ignore me\n", encoding="utf-8")

        hashes = service._hash_indexable_files(repo_path)

    assert hashes == {"app.py": _sha("print('hello')\n")}


def test_finalize_benchmark_adds_duration_speedup_estimate():
    service = EmbeddingService(FakeDB())
    stats = {
        "duration_ms": 100,
        "benchmark": {
            "baseline_full_reindex_files": 10,
            "incremental_candidate_files": 2,
        },
    }

    service._finalize_benchmark(stats)

    assert stats["benchmark"]["incremental_duration_ms"] == 100
    assert stats["benchmark"]["estimated_full_reindex_duration_ms"] == 500
    assert stats["benchmark"]["estimated_speedup_factor"] == 5.0


def test_detect_git_changes_reads_last_commit_history():
    service = EmbeddingService(FakeDB())
    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        repo = Repo.init(repo_path)
        with repo.config_writer() as config:
            config.set_value("user", "name", "CodePilot")
            config.set_value("user", "email", "codepilot@example.com")

        (repo_path / "keep.py").write_text("print('old')\n", encoding="utf-8")
        (repo_path / "remove.py").write_text("print('bye')\n", encoding="utf-8")
        repo.index.add(["keep.py", "remove.py"])
        repo.index.commit("initial")

        (repo_path / "keep.py").write_text("print('new')\n", encoding="utf-8")
        (repo_path / "remove.py").unlink()
        (repo_path / "new.py").write_text("print('new file')\n", encoding="utf-8")
        repo.index.add(["keep.py", "new.py"])
        repo.index.remove(["remove.py"])
        repo.index.commit("change files")

        changed, deleted = service._detect_git_changes(repo_path)

    assert changed == {"keep.py", "new.py"}
    assert deleted == {"remove.py"}


@pytest.mark.asyncio
async def test_build_indexing_plan_combines_hashes_and_deleted_files(monkeypatch):
    service = EmbeddingService(FakeDB())
    repo_id = uuid.uuid4()

    with tempfile.TemporaryDirectory() as tmp:
        repo_path = Path(tmp)
        (repo_path / "same.py").write_text("same\n", encoding="utf-8")
        (repo_path / "changed.py").write_text("new\n", encoding="utf-8")
        (repo_path / "added.py").write_text("added\n", encoding="utf-8")

        monkeypatch.setattr(
            service,
            "_load_existing_hashes",
            AsyncMock(
                return_value={
                    "same.py": _sha("same\n"),
                    "changed.py": _sha("old\n"),
                    "deleted.py": _sha("deleted\n"),
                }
            ),
        )
        monkeypatch.setattr(
            service,
            "_detect_git_changes",
            MagicMock(return_value=({"changed.py", "added.py"}, {"deleted.py"})),
        )

        plan = await service._build_indexing_plan(repo_id, repo_path)

    assert plan.modified_files == ["added.py", "changed.py"]
    assert plan.deleted_files == ["deleted.py"]
    assert plan.unchanged_files == ["same.py"]
    assert plan.git_history_available is True


@pytest.mark.asyncio
async def test_with_retries_retries_transient_failures(monkeypatch):
    service = EmbeddingService(FakeDB())
    service.settings.embedding_max_retries = 3
    service.settings.embedding_backoff_base = 0

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr("app.services.embedding_service.asyncio.sleep", fake_sleep)

    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("try again")
        return "ok"

    result = await service._with_retries("test", flaky)

    assert result == "ok"
    assert attempts["count"] == 3


@pytest.mark.asyncio
async def test_process_modified_batch_replaces_vectors_and_hashes(monkeypatch):
    db = FakeDB()
    service = EmbeddingService(db)
    repo_id = uuid.uuid4()
    deleted_files = []
    indexed_chunks = []

    class FakeVectorStore:
        def delete_repository_file(self, repository_id, file_path):
            deleted_files.append((repository_id, file_path))

        async def index_chunks(self, repository_id, chunks):
            indexed_chunks.extend(chunks)
            return len(chunks)

    service.vector_store = FakeVectorStore()
    monkeypatch.setattr(
        service,
        "_chunk_file",
        lambda repo_path, file_path: [
            CodeChunk(
                content="def changed():\n    return True\n",
                file_path=file_path,
                chunk_type="function",
                language="python",
                symbol_name="changed",
                start_line=1,
                end_line=2,
            )
        ],
    )

    vectors = await service._process_modified_batch(
        repository_id=repo_id,
        repo_path=Path("/unused"),
        file_paths=["app.py"],
        current_hashes={"app.py": _sha("new\n")},
    )

    assert vectors == 1
    assert deleted_files == [(str(repo_id), "app.py")]
    assert len(indexed_chunks) == 1
    assert len(db.added) == 2  # one EmbeddingRecord and one RepositoryFileHash
