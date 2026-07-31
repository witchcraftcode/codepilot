"""GitHub repository cloning and loading."""

import re
import shutil
import asyncio
from pathlib import Path
from typing import Sequence
from uuid import UUID

from git import Repo

from app.config import get_settings


class RepositoryLoader:
    GITHUB_URL_PATTERN = re.compile(
        r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
    )

    def __init__(self) -> None:
        self.settings = get_settings()
        self.clone_dir = Path(self.settings.repo_clone_dir)
        self.clone_dir.mkdir(parents=True, exist_ok=True)

    def parse_github_url(self, url: str) -> tuple[str, str]:
        match = self.GITHUB_URL_PATTERN.match(url.strip())
        if not match:
            raise ValueError(f"Invalid GitHub URL: {url}")
        return match.group("owner"), match.group("repo")

    def get_repo_path(self, repository_id: UUID) -> Path:
        return self.clone_dir / str(repository_id)

    async def clone(self, github_url: str, repository_id: UUID, branch: str | None = None) -> Path:
        owner, repo = self.parse_github_url(github_url)
        target = self.get_repo_path(repository_id)

        if target.exists():
            shutil.rmtree(target)

        def clone_repo() -> None:
            kwargs = {"depth": 1}
            if branch:
                kwargs["branch"] = branch
            Repo.clone_from(github_url, str(target), **kwargs)

        await asyncio.to_thread(clone_repo)
        return target

    def get_folder_structure(self, repo_path: Path, max_depth: int = 3) -> dict:
        def build_tree(path: Path, depth: int = 0) -> dict:
            if depth > max_depth:
                return {"type": "truncated"}
            if path.is_file():
                return {"type": "file", "name": path.name}
            children = {}
            try:
                for child in sorted(path.iterdir()):
                    if child.name.startswith(".") and child.name != ".env.example":
                        continue
                    if child.name in {"node_modules", "venv", "__pycache__", "dist", "build"}:
                        continue
                    children[child.name] = build_tree(child, depth + 1)
            except PermissionError:
                pass
            return {"type": "directory", "name": path.name, "children": children}

        return build_tree(repo_path)
