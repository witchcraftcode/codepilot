"""Retrieve repository context for changed files."""

from typing import Any

from app.services.retrieval_service import RetrievalService


class PRContextService:
    def __init__(self):
        self.retrieval = RetrievalService()

    async def retrieve(
        self,
        repository_id: str,
        filename: str,
        patch: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Returns the most relevant repository chunks for a git diff.
        """

        query = f"{filename}\n{patch}"

        results = await self.retrieval.search(
            repository_id=repository_id,
            query=query,
            limit=top_k,
        )

        return results