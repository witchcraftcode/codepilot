"""Repository indexing service orchestrating repository embedding."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.services.embedding_service import EmbeddingService


class IndexingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.embedding_service = EmbeddingService(db)

    async def index_repository(self, repository_id: UUID, branch: str | None = None) -> Repository:
        result = await self.db.execute(select(Repository).where(Repository.id == repository_id))
        repo = result.scalar_one()
        await self.embedding_service.embed_repository(repository_id, branch)
        return repo
