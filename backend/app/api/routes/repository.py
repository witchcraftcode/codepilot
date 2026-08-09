"""Repository API routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models.repository import Repository
from app.models.user import User
from app.schemas import (
    RepositoryCreate,
    RepositoryEmbedRequest,
    RepositoryEmbedResponse,
    RepositoryListResponse,
    RepositoryResponse,
)
from app.services.indexing import IndexingService

router = APIRouter(prefix="/repository", tags=["repository"])


async def _index_background(repository_id: UUID, branch: str | None, db_url: str) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

    engine = create_async_engine(db_url)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        service = IndexingService(session)
        await service.index_repository(repository_id, branch)
        await session.commit()


@router.post("", response_model=RepositoryResponse, status_code=201)
async def create_repository(
    body: RepositoryCreate,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    github_url = str(body.github_url)
    existing = await db.execute(select(Repository).where(Repository.github_url == github_url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Repository already indexed")

    from parsers.repository_loader import RepositoryLoader

    loader = RepositoryLoader()
    owner, repo_name = loader.parse_github_url(github_url)

    repository = Repository(
        owner_id=user.id,
        github_url=github_url,
        name=repo_name,
        full_name=f"{owner}/{repo_name}",
        default_branch=body.branch or "main",
        status="pending",
    )
    db.add(repository)
    await db.flush()

    from app.config import get_settings

    settings = get_settings()
    background_tasks.add_task(_index_background, repository.id, body.branch, settings.database_url)

    return repository


@router.post("/embed", response_model=RepositoryEmbedResponse, status_code=202)
async def embed_repository(
    body: RepositoryEmbedRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Repository).where(Repository.id == body.repository_id, Repository.owner_id == user.id)
    )
    repository = result.scalar_one_or_none()
    if not repository:
        raise HTTPException(status_code=404, detail="Repository not found")

    from app.services.embedding_service import EmbeddingService

    service = EmbeddingService(db)
    stats = await service.embed_repository(repository.id, body.branch)
    return stats


@router.post("/index", status_code=201)
async def index_repository(
    body: RepositoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Validate, clone, analyze and index repository metadata (no embeddings).

    Steps:
    1. Validate GitHub URL
    2. Clone into a temporary folder using GitPython
    3. Ignore common folders (.git, node_modules, dist, build, venv, __pycache__)
    4. Detect language by file extensions
    5. Extract supported files and store metadata in the repositories table
    """
    github_url = str(body.github_url)
    existing = await db.execute(select(Repository).where(Repository.github_url == github_url))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Repository already indexed")

    # Use the repository loader only for URL parsing
    from parsers.repository_loader import RepositoryLoader
    from git import Repo
    import tempfile
    import asyncio
    import os
    from pathlib import Path
    from datetime import datetime, timezone

    loader = RepositoryLoader()
    owner, repo_name = loader.parse_github_url(github_url)

    repository = Repository(
        owner_id=user.id,
        github_url=github_url,
        name=repo_name,
        full_name=f"{owner}/{repo_name}",
        default_branch=body.branch or "main",
        status="indexing",
    )
    db.add(repository)
    await db.flush()

    # Clone into temporary folder (blocking I/O in thread)
    tmp_dir = tempfile.TemporaryDirectory()
    repo_path = Path(tmp_dir.name)

    def _clone():
        kwargs = {"depth": 1}
        if body.branch:
            kwargs["branch"] = body.branch
        Repo.clone_from(github_url, str(repo_path), **kwargs)

    try:
        await asyncio.to_thread(_clone)
    except Exception as e:
        repository.status = "error"
        repository.error_message = str(e)
        await db.flush()
        tmp_dir.cleanup()
        raise HTTPException(status_code=500, detail=f"Failed to clone repository: {e}")

    # Analyze files (run in thread because of filesystem I/O)
    IGNORED_DIRS = {".git", "node_modules", "dist", "build", "venv", "__pycache__"}

    SUPPORTED_EXTENSIONS = {
        "Python": {".py"},
        "JavaScript": {".js"},
        "TypeScript": {".ts", ".tsx"},
        "Java": {".java"},
        "C++": {".cpp", ".cc", ".cxx", ".h", ".hpp", ".c"},
        "Markdown": {".md", ".markdown"},
    }

    ext_to_lang = {}
    for lang, exts in SUPPORTED_EXTENSIONS.items():
        for e in exts:
            ext_to_lang[e] = lang

    def _analyze_files(path: Path) -> tuple[dict, int]:
        language_counts: dict = {}
        files_indexed = 0
        for root, dirs, files in os.walk(path):
            # filter out ignored directories in-place to avoid walking them
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith('.')]
            # skip .git at top-level as well
            if os.path.basename(root) in IGNORED_DIRS:
                continue
            for f in files:
                if f.startswith('.'):
                    continue
                _, ext = os.path.splitext(f)
                lang = ext_to_lang.get(ext.lower())
                if lang:
                    language_counts[lang] = language_counts.get(lang, 0) + 1
                    files_indexed += 1
        return language_counts, files_indexed

    try:
        language_summary, files_indexed = await asyncio.to_thread(_analyze_files, repo_path)
    finally:
        # cleanup clone
        tmp_dir.cleanup()

    # Persist metadata
    repository.languages = language_summary
    repository.file_count = files_indexed
    repository.status = "ready"
    repository.indexed_at = datetime.now(timezone.utc)
    repository.overview = (
        f"Repository with {files_indexed} supported files. "
        f"Languages: {', '.join(f'{k} ({v} files)' for k, v in (language_summary or {}).items())}."
    )

    await db.flush()

    return {"repository_id": str(repository.id), "language_summary": repository.languages or {}, "files_indexed": repository.file_count}


@router.get("", response_model=RepositoryListResponse)
async def list_repositories(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    skip: int = 0,
    limit: int = 20,
):
    count_result = await db.execute(
        select(func.count()).select_from(Repository).where(Repository.owner_id == user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(Repository)
        .where(Repository.owner_id == user.id)
        .order_by(Repository.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    repos = result.scalars().all()
    return RepositoryListResponse(repositories=repos, total=total)


@router.get("/{repository_id}", response_model=RepositoryResponse)
async def get_repository(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(
        select(Repository).where(Repository.id == repository_id, Repository.owner_id == user.id)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
