"""Repository indexing service orchestrating clone, parse, chunk, embed."""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import EmbeddingRecord
from app.models.repository import Repository
from parsers.chunker import CodeChunker
from parsers.repository_loader import RepositoryLoader
from parsers.repository_parser import RepositoryParser
from vectorstore.qdrant_store import VectorStore


class IndexingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.loader = RepositoryLoader()
        self.parser = RepositoryParser()
        self.chunker = CodeChunker()
        self.vector_store = VectorStore()

    async def index_repository(self, repository_id: UUID, branch: str | None = None) -> Repository:
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = result.scalar_one()

        repo.status = "indexing"
        await self.db.flush()

        try:
            repo_path = await self.loader.clone(repo.github_url, repository_id, branch)
            metadata = self.parser.parse(repo_path)
            chunks = self.chunker.chunk_repository(repo_path)
            chunk_count = await self.vector_store.index_chunks(str(repository_id), chunks)

            for chunk in chunks[:chunk_count]:
                record = EmbeddingRecord(
                    repository_id=repository_id,
                    vector_id=hashlib.sha256(chunk.content.encode()).hexdigest()[:32],
                    file_path=chunk.file_path,
                    chunk_type=chunk.chunk_type,
                    language=chunk.language,
                    symbol_name=chunk.symbol_name,
                    content_hash=hashlib.sha256(chunk.content.encode()).hexdigest(),
                    content_preview=chunk.content[:500],
                    metadata_={
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "parent_symbol": chunk.parent_symbol,
                    },
                )
                self.db.add(record)

            repo.languages = metadata["languages"]
            repo.frameworks = metadata["frameworks"]
            repo.dependencies = metadata["dependencies"]
            repo.file_count = metadata["file_count"]
            repo.chunk_count = chunk_count
            repo.status = "ready"
            repo.indexed_at = datetime.now(timezone.utc)
            repo.overview = self._generate_overview(metadata)

        except Exception as e:
            repo.status = "error"
            repo.error_message = str(e)
            raise

        await self.db.flush()
        return repo

    def _generate_overview(self, metadata: dict) -> str:
        langs = ", ".join(f"{k} ({v} files)" for k, v in metadata.get("languages", {}).items())
        frameworks = ", ".join(metadata.get("frameworks", [])) or "None detected"
        return f"Repository with {metadata.get('file_count', 0)} files. Languages: {langs}. Frameworks: {frameworks}."
