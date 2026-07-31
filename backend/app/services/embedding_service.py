"""Repository embedding pipeline and Qdrant indexing service."""

import asyncio
import hashlib
from uuid import UUID
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EmbeddingRecord
from app.models.repository import Repository
from app.models.repository_file_hash import RepositoryFileHash
from app.parsers.repository_loader import RepositoryLoader
from app.parsers.repository_parser import RepositoryParser
from parsers.language_utils import detect_language
from parsers.chunker import CodeChunk
from vectorstore.qdrant_store import VectorStore


class EmbeddingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.loader = RepositoryLoader()
        self.parser = RepositoryParser()
        self.vector_store = VectorStore()

    async def embed_repository(self, repository_id: UUID, branch: str | None = None) -> dict[str, int]:
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repository = result.scalar_one()

        repository.status = "indexing"
        await self.db.flush()

        try:
            repo_path = await self.loader.clone(repository.github_url, repository_id, branch or repository.default_branch)
            file_units = await asyncio.to_thread(self.parser.parse_structure, repo_path)

            existing_hashes = await self._load_existing_hashes(repository_id)
            files_indexed = 0
            files_skipped = 0
            vectors_indexed = 0

            for file_path, file_data in file_units["files"].items():
                target_path = repo_path / file_path
                if not target_path.exists():
                    continue

                file_hash = self._compute_file_hash(target_path)
                if existing_hashes.get(file_path) == file_hash:
                    files_skipped += 1
                    continue

                self.vector_store.delete_repository_file(str(repository_id), file_path)
                await self._delete_embedding_records(repository_id, file_path)

                units = self._build_code_chunks(file_path, file_data)
                if not units:
                    files_skipped += 1
                    await self._upsert_file_hash(repository_id, file_path, file_hash)
                    continue

                indexed = await self.vector_store.index_chunks(str(repository_id), units)
                vectors_indexed += indexed
                files_indexed += 1
                await self._save_embedding_records(repository_id, units)
                await self._upsert_file_hash(repository_id, file_path, file_hash)

            repository.status = "ready"
            await self.db.flush()
            return {
                "repository_id": str(repository_id),
                "files_indexed": files_indexed,
                "files_skipped": files_skipped,
                "vectors_indexed": vectors_indexed,
            }
        except Exception as exc:
            repository.status = "error"
            repository.error_message = str(exc)
            await self.db.flush()
            raise

    async def _load_existing_hashes(self, repository_id: UUID) -> dict[str, str]:
        result = await self.db.execute(
            select(RepositoryFileHash.file_path, RepositoryFileHash.file_hash).where(
                RepositoryFileHash.repository_id == repository_id
            )
        )
        return {row.file_path: row.file_hash for row in result.all()}

    def _compute_file_hash(self, file_path: Path) -> str:
        content = file_path.read_bytes()
        return hashlib.sha256(content).hexdigest()

    async def _delete_embedding_records(self, repository_id: UUID, file_path: str) -> None:
        await self.db.execute(
            delete(EmbeddingRecord).where(
                EmbeddingRecord.repository_id == repository_id,
                EmbeddingRecord.file_path == file_path,
            )
        )

    async def _save_embedding_records(self, repository_id: UUID, units: list[CodeChunk]) -> None:
        for chunk in units:
            record = EmbeddingRecord(
                repository_id=repository_id,
                vector_id=hashlib.sha256(chunk.content.encode()).hexdigest()[:32],
                file_path=chunk.file_path,
                chunk_type=chunk.chunk_type,
                language=chunk.language,
                symbol_name=chunk.symbol_name,
                content_hash=hashlib.sha256(chunk.content.encode()).hexdigest(),
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
            record.file_hash = file_hash
        else:
            self.db.add(
                RepositoryFileHash(
                    repository_id=repository_id,
                    file_path=file_path,
                    file_hash=file_hash,
                )
            )
        await self.db.flush()

    def _build_code_chunks(self, file_path: str, file_data: dict) -> list[CodeChunk]:
        language = file_data.get("language") or detect_language(file_path) or ""
        chunks: list[CodeChunk] = []
        for unit in file_data.get("classes", []) + file_data.get("functions", []) + file_data.get("methods", []):
            content = unit.get("content", "")
            if not content.strip():
                continue
            chunks.append(
                CodeChunk(
                    content=content,
                    file_path=file_path,
                    chunk_type=unit.get("symbol_type", "file"),
                    language=language,
                    symbol_name=unit.get("name"),
                    parent_symbol=unit.get("parent_class"),
                    start_line=unit.get("start_line", 1),
                    end_line=unit.get("end_line", 1),
                )
            )
        return chunks
