"""Repository embedding pipeline and Qdrant indexing service."""

import asyncio
import hashlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID
from pathlib import Path

from git import Repo
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.embedding import EmbeddingRecord
from app.models.repository import Repository
from app.models.repository_file_hash import RepositoryFileHash
from parsers.chunker import CodeChunk, CodeChunker
from parsers.language_utils import detect_language, should_ignore_path
from parsers.repository_loader import RepositoryLoader
from parsers.repository_parser import RepositoryParser
from vectorstore.qdrant_store import VectorStore

logger = logging.getLogger("codepilot.indexing")
ProgressCallback = Callable[[dict], Awaitable[None] | None]


@dataclass(frozen=True)
class IndexingPlan:
    current_hashes: dict[str, str]
    existing_hashes: dict[str, str]
    modified_files: list[str]
    deleted_files: list[str]
    unchanged_files: list[str]
    git_changed_files: list[str]
    git_deleted_files: list[str]
    git_history_available: bool


class EmbeddingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()
        self.loader = RepositoryLoader()
        self.parser = RepositoryParser()
        self.chunker = CodeChunker()
        self.vector_store = VectorStore()

    async def embed_repository(
        self,
        repository_id: UUID,
        branch: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict:
        """Incrementally embed a repository using git history and SHA256 file hashes."""
        start_time = time.perf_counter()
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repository = result.scalar_one()

        repository.status = "indexing"
        await self.db.flush()
        await self._emit_progress(
            progress_callback,
            repository_id,
            "started",
            "Repository indexing started",
        )

        try:
            repo_path = await self.loader.clone(
                repository.github_url,
                repository_id,
                branch or repository.default_branch,
            )
            metadata = await asyncio.to_thread(self.parser.parse, repo_path)
            plan = await self._build_indexing_plan(repository_id, repo_path)
            batch_size = max(1, self.settings.repository_index_batch_size)
            batches = self._batch(plan.modified_files, batch_size)

            stats = {
                "repository_id": str(repository_id),
                "files_indexed": 0,
                "files_skipped": 0,
                "files_deleted": 0,
                "files_unchanged": len(plan.unchanged_files),
                "vectors_indexed": 0,
                "batches_processed": 0,
                "duration_ms": 0,
                "benchmark": self._benchmark(plan, metadata),
            }

            logger.info(
                "repository.index.plan",
                extra={
                    "repository_id": str(repository_id),
                    "modified_files": len(plan.modified_files),
                    "deleted_files": len(plan.deleted_files),
                    "unchanged_files": len(plan.unchanged_files),
                    "git_history_available": plan.git_history_available,
                },
            )
            await self._emit_progress(
                progress_callback,
                repository_id,
                "planned",
                "Repository changes detected",
                stats=stats,
                modified_files=len(plan.modified_files),
                deleted_files=len(plan.deleted_files),
                unchanged_files=len(plan.unchanged_files),
            )

            async with self.db.begin_nested():
                for file_path in plan.deleted_files:
                    await self._replace_file_vectors(repository_id, file_path, [])
                    await self._delete_file_hash(repository_id, file_path)
                    stats["files_deleted"] += 1

                if plan.deleted_files:
                    await self._emit_progress(
                        progress_callback,
                        repository_id,
                        "deleted",
                        "Deleted-file vectors removed",
                        deleted_files=stats["files_deleted"],
                    )

                for batch_number, file_batch in enumerate(batches, start=1):
                    vectors = await self._process_modified_batch(
                        repository_id=repository_id,
                        repo_path=repo_path,
                        file_paths=file_batch,
                        current_hashes=plan.current_hashes,
                    )
                    stats["vectors_indexed"] += vectors
                    stats["files_indexed"] += len(file_batch)
                    stats["batches_processed"] += 1
                    await self._emit_progress(
                        progress_callback,
                        repository_id,
                        "batch_completed",
                        "Indexing batch completed",
                        batch_number=batch_number,
                        batch_count=len(batches),
                        files_indexed=stats["files_indexed"],
                        vectors_indexed=stats["vectors_indexed"],
                    )

                stats["files_skipped"] = stats["files_unchanged"]
                stats["total_vectors"] = await self._count_embedding_records(repository_id)
                self._update_repository_metadata(repository, metadata, stats)

            stats["duration_ms"] = int((time.perf_counter() - start_time) * 1000)
            self._finalize_benchmark(stats)
            repository.status = "ready"
            repository.error_message = None
            await self.db.flush()
            await self._emit_progress(
                progress_callback,
                repository_id,
                "completed",
                "Repository indexing completed",
                stats=stats,
            )
            logger.info(
                "repository.index.completed",
                extra={"repository_id": str(repository_id), **stats},
            )
            return stats
        except Exception as exc:
            repository.status = "error"
            repository.error_message = str(exc)
            await self.db.flush()
            await self._emit_progress(
                progress_callback,
                repository_id,
                "failed",
                "Repository indexing failed",
                error=str(exc),
            )
            logger.exception(
                "repository.index.failed",
                extra={"repository_id": str(repository_id), "error": str(exc)},
            )
            raise

    async def _build_indexing_plan(self, repository_id: UUID, repo_path: Path) -> IndexingPlan:
        existing_hashes = await self._load_existing_hashes(repository_id)
        current_hashes = await asyncio.to_thread(self._hash_indexable_files, repo_path)
        git_changes = await asyncio.to_thread(self._detect_git_changes, repo_path)
        git_changed_files: set[str] = set()
        git_deleted_files: set[str] = set()
        git_history_available = git_changes is not None
        if git_changes is not None:
            git_changed_files, git_deleted_files = git_changes

        current_paths = set(current_hashes)
        existing_paths = set(existing_hashes)
        deleted_files = sorted(existing_paths - current_paths)
        if git_history_available:
            deleted_files = sorted(set(deleted_files) | (git_deleted_files & existing_paths))

        modified_files = sorted(
            file_path
            for file_path, file_hash in current_hashes.items()
            if existing_hashes.get(file_path) != file_hash
        )
        unchanged_files = sorted(current_paths - set(modified_files))

        return IndexingPlan(
            current_hashes=current_hashes,
            existing_hashes=existing_hashes,
            modified_files=modified_files,
            deleted_files=deleted_files,
            unchanged_files=unchanged_files,
            git_changed_files=sorted(git_changed_files),
            git_deleted_files=sorted(git_deleted_files),
            git_history_available=git_history_available,
        )

    async def _load_existing_hashes(self, repository_id: UUID) -> dict[str, str]:
        result = await self.db.execute(
            select(RepositoryFileHash.file_path, RepositoryFileHash.sha256).where(
                RepositoryFileHash.repository_id == repository_id
            )
        )
        return {row.file_path: row.sha256 for row in result.all()}

    def _compute_file_hash(self, file_path: Path) -> str:
        content = file_path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    def _hash_indexable_files(self, repo_path: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for file_path in sorted(repo_path.rglob("*")):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(repo_path)
            if should_ignore_path(rel_path):
                continue
            language = detect_language(str(file_path))
            if not language:
                continue
            hashes[str(rel_path)] = self._compute_file_hash(file_path)
        return hashes

    def _detect_git_changes(self, repo_path: Path) -> tuple[set[str], set[str]] | None:
        try:
            repo = Repo(repo_path)
            repo.commit("HEAD~1")
            diff_output = repo.git.diff("--name-status", "HEAD~1..HEAD")
        except Exception:
            return None

        changed: set[str] = set()
        deleted: set[str] = set()
        for line in diff_output.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0]
            if status.startswith("D"):
                deleted.add(parts[1])
            elif status.startswith("R") and len(parts) >= 3:
                deleted.add(parts[1])
                changed.add(parts[2])
            else:
                changed.add(parts[-1])
        return changed, deleted

    async def _process_modified_batch(
        self,
        repository_id: UUID,
        repo_path: Path,
        file_paths: list[str],
        current_hashes: dict[str, str],
    ) -> int:
        vectors_indexed = 0
        for file_path in file_paths:
            chunks = await asyncio.to_thread(self._chunk_file, repo_path, file_path)
            indexed = await self._replace_file_vectors(repository_id, file_path, chunks)
            vectors_indexed += indexed
            await self._upsert_file_hash(repository_id, file_path, current_hashes[file_path])
        return vectors_indexed

    def _chunk_file(self, repo_path: Path, file_path: str) -> list[CodeChunk]:
        target_path = repo_path / file_path
        language = detect_language(str(target_path)) or ""
        if not target_path.exists() or not language:
            return []
        return self.chunker.chunk_file(target_path, file_path, language)

    async def _replace_file_vectors(
        self,
        repository_id: UUID,
        file_path: str,
        chunks: list[CodeChunk],
    ) -> int:
        await self._with_retries(
            f"qdrant.delete_file:{file_path}",
            lambda: self.vector_store.delete_repository_file(str(repository_id), file_path),
        )
        await self._delete_embedding_records(repository_id, file_path)
        if not chunks:
            return 0

        indexed = await self._with_retries(
            f"qdrant.index_file:{file_path}",
            lambda: self.vector_store.index_chunks(str(repository_id), chunks),
        )
        await self._save_embedding_records(repository_id, chunks)
        return int(indexed or 0)

    async def _with_retries(self, operation: str, func: Callable[[], object]) -> object:
        max_attempts = max(1, self.settings.embedding_max_retries)
        for attempt in range(1, max_attempts + 1):
            try:
                result = func()
                if inspect.isawaitable(result):
                    return await result
                return result
            except Exception:
                if attempt >= max_attempts:
                    logger.exception(
                        "repository.index.retry_exhausted",
                        extra={"operation": operation, "attempt": attempt},
                    )
                    raise
                delay = self.settings.embedding_backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "repository.index.retry",
                    extra={"operation": operation, "attempt": attempt, "delay_seconds": delay},
                )
                await asyncio.sleep(delay)

    async def _delete_embedding_records(self, repository_id: UUID, file_path: str) -> None:
        await self.db.execute(
            delete(EmbeddingRecord).where(
                EmbeddingRecord.repository_id == repository_id,
                EmbeddingRecord.file_path == file_path,
            )
        )

    async def _save_embedding_records(self, repository_id: UUID, units: list[CodeChunk]) -> None:
        for chunk in units:
            content_hash = hashlib.sha256(chunk.content.encode()).hexdigest()
            record = EmbeddingRecord(
                repository_id=repository_id,
                vector_id=content_hash[:32],
                file_path=chunk.file_path,
                chunk_type=chunk.chunk_type,
                language=chunk.language,
                symbol_name=chunk.symbol_name,
                content_hash=content_hash,
                metadata_={
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "parent_symbol": chunk.parent_symbol,
                },
                content_preview=chunk.content[:500],
            )
            self.db.add(record)
        await self.db.flush()

    async def _upsert_file_hash(self, repository_id: UUID, file_path: str, file_hash: str) -> None:
        existing = await self.db.execute(
            select(RepositoryFileHash).where(
                RepositoryFileHash.repository_id == repository_id,
                RepositoryFileHash.file_path == file_path,
            )
        )
        record = existing.scalar_one_or_none()
        if record:
            record.sha256 = file_hash
        else:
            self.db.add(
                RepositoryFileHash(
                    repository_id=repository_id,
                    file_path=file_path,
                    sha256=file_hash,
                )
            )
        await self.db.flush()

    async def _delete_file_hash(self, repository_id: UUID, file_path: str) -> None:
        await self.db.execute(
            delete(RepositoryFileHash).where(
                RepositoryFileHash.repository_id == repository_id,
                RepositoryFileHash.file_path == file_path,
            )
        )
        await self.db.flush()

    async def _count_embedding_records(self, repository_id: UUID) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(EmbeddingRecord).where(
                EmbeddingRecord.repository_id == repository_id
            )
        )
        return int(result.scalar() or 0)

    def _update_repository_metadata(self, repository: Repository, metadata: dict, stats: dict) -> None:
        repository.languages = metadata.get("languages", {})
        repository.frameworks = metadata.get("frameworks", [])
        repository.dependencies = metadata.get("dependencies", {})
        repository.file_count = metadata.get("file_count", 0)
        repository.chunk_count = int(stats.get("total_vectors", stats.get("vectors_indexed", 0)))
        repository.indexed_at = datetime_now_utc()
        repository.overview = self._generate_overview(metadata, stats)

    def _benchmark(self, plan: IndexingPlan, metadata: dict) -> dict:
        full_reindex_files = len(plan.current_hashes)
        incremental_files = len(plan.modified_files) + len(plan.deleted_files)
        avoided_files = max(full_reindex_files - incremental_files, 0)
        reembed_ratio = round(incremental_files / full_reindex_files, 4) if full_reindex_files else 0.0
        return {
            "baseline_full_reindex_files": full_reindex_files,
            "incremental_candidate_files": incremental_files,
            "files_avoided": avoided_files,
            "reembed_ratio": reembed_ratio,
            "metadata_file_count": metadata.get("file_count", 0),
            "git_history_available": plan.git_history_available,
            "git_changed_files": len(plan.git_changed_files),
            "git_deleted_files": len(plan.git_deleted_files),
        }

    def _finalize_benchmark(self, stats: dict) -> None:
        benchmark = stats.get("benchmark") or {}
        incremental_files = max(int(benchmark.get("incremental_candidate_files", 0)), 1)
        full_reindex_files = int(benchmark.get("baseline_full_reindex_files", 0))
        incremental_duration_ms = int(stats.get("duration_ms") or 0)
        estimated_full_duration_ms = int(
            incremental_duration_ms * (full_reindex_files / incremental_files)
        ) if full_reindex_files else 0
        benchmark.update(
            {
                "incremental_duration_ms": incremental_duration_ms,
                "estimated_full_reindex_duration_ms": estimated_full_duration_ms,
                "estimated_speedup_factor": round(
                    estimated_full_duration_ms / incremental_duration_ms,
                    2,
                )
                if incremental_duration_ms
                else 0.0,
            }
        )

    def _generate_overview(self, metadata: dict, stats: dict) -> str:
        langs = ", ".join(f"{k} ({v} files)" for k, v in metadata.get("languages", {}).items())
        if not langs:
            langs = "No supported languages detected"
        return (
            f"Repository indexed incrementally. Languages: {langs}. "
            f"Re-embedded {stats.get('files_indexed', 0)} files, "
            f"removed {stats.get('files_deleted', 0)} deleted files, "
            f"skipped {stats.get('files_unchanged', 0)} unchanged files."
        )

    def _batch(self, items: list[str], batch_size: int) -> list[list[str]]:
        return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

    async def _emit_progress(
        self,
        progress_callback: ProgressCallback | None,
        repository_id: UUID,
        stage: str,
        message: str,
        **payload,
    ) -> None:
        event = {
            "repository_id": str(repository_id),
            "stage": stage,
            "message": message,
            **payload,
        }
        logger.info("repository.index.progress", extra=event)
        if progress_callback is None:
            return
        result = progress_callback(event)
        if inspect.isawaitable(result):
            await result


def datetime_now_utc():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
