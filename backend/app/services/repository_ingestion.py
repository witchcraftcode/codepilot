from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository
from app.parsers.language_utils import detect_language, should_ignore_path
from app.parsers.repository_loader import RepositoryLoader
from app.parsers.repository_parser import RepositoryParser

logger = logging.getLogger("codepilot.ingestion")
SUPPORTED_INGESTION_LANGUAGES = {"python", "javascript", "typescript", "java", "cpp", "markdown"}


class RepositoryIngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.loader = RepositoryLoader()
        self.parser = RepositoryParser()

    async def ingest(self, user_id: UUID, github_url: str, branch: str | None = None) -> tuple[Repository, int]:
        repository = Repository(
            owner_id=user_id,
            github_url=github_url,
            name="",
            full_name="",
            default_branch=branch or "main",
            status="pending",
        )
        self.db.add(repository)
        await self.db.flush()

        try:
            repo_path = await self.loader.clone(github_url, repository.id, branch)
            metadata = await asyncio.to_thread(self.parser.parse, repo_path)
            language_summary = self._filter_supported_languages(metadata.get("languages", {}))
            file_count = await asyncio.to_thread(self._count_supported_files, repo_path)

            repository.name = repo_path.name
            repository.full_name = repository.name
            repository.languages = language_summary
            repository.file_count = file_count
            repository.status = "ready"
            repository.indexed_at = datetime.now(timezone.utc)
            repository.overview = self._build_overview(language_summary, file_count)

            logger.info("repository.ingested", repository_id=str(repository.id), file_count=file_count)
        except Exception as exc:
            repository.status = "error"
            repository.error_message = str(exc)
            await self.db.flush()
            logger.exception("repository.ingestion_failed", repository_id=str(repository.id))
            raise

        await self.db.flush()
        return repository, file_count

    def _count_supported_files(self, repo_path: Path) -> int:
        total = 0
        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(repo_path)
            if should_ignore_path(rel):
                continue
            lang = detect_language(str(file_path))
            if lang in SUPPORTED_INGESTION_LANGUAGES:
                total += 1
        return total

    def _filter_supported_languages(self, languages: dict[str, int]) -> dict[str, int]:
        return {lang: count for lang, count in languages.items() if lang in SUPPORTED_INGESTION_LANGUAGES}

    def _build_overview(self, language_summary: dict[str, int], file_count: int) -> str:
        languages = ", ".join(f"{lang} ({count})" for lang, count in sorted(language_summary.items()))
        if not languages:
            languages = "No supported languages detected"
        return f"Indexed {file_count} supported files. Languages: {languages}."
