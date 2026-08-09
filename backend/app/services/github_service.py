"""GitHub API client for pull request operations."""

import re
from dataclasses import dataclass

import httpx

from app.config import get_settings
from parsers.repository_loader import RepositoryLoader

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


@dataclass
class PullRequestData:
    number: int
    title: str
    body: str | None
    html_url: str
    base_branch: str
    head_branch: str
    state: str
    diff: str
    files: list[dict]


class GitHubServiceError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitHubService:
    """Fetch pull request data from the GitHub REST API."""

    REPO_PATTERN = re.compile(
        r"^(?:https?://github\.com/)?(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
    )

    def __init__(self, access_token: str | None = None) -> None:
        settings = get_settings()
        self.access_token = access_token or getattr(settings, "github_token", None) or None

    def parse_repository(self, repository: str) -> tuple[str, str]:
        """Parse owner/repo from a repository string or GitHub URL."""
        repository = repository.strip()
        match = self.REPO_PATTERN.match(repository)
        if match:
            return match.group("owner"), match.group("repo")

        loader = RepositoryLoader()
        return loader.parse_github_url(repository)

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def fetch_pull_request(
        self,
        owner: str,
        repo: str,
        pull_request_number: int,
    ) -> PullRequestData:
        """Fetch PR metadata, diff, and changed files."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            pr_resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_request_number}",
                headers=self._headers(),
            )
            if pr_resp.status_code == 404:
                raise GitHubServiceError(
                    f"Pull request #{pull_request_number} not found in {owner}/{repo}",
                    status_code=404,
                )
            if pr_resp.status_code == 401:
                raise GitHubServiceError(
                    "GitHub authentication required for this repository. "
                    "Sign in with GitHub or provide a valid access token.",
                    status_code=401,
                )
            if pr_resp.status_code == 403:
                raise GitHubServiceError(
                    "GitHub API rate limit exceeded or access forbidden. "
                    "Authenticate for higher rate limits.",
                    status_code=403,
                )
            if pr_resp.status_code != 200:
                raise GitHubServiceError(
                    f"GitHub API error: {pr_resp.text}",
                    status_code=pr_resp.status_code,
                )

            pr_data = pr_resp.json()

            diff_resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_request_number}",
                headers=self._headers("application/vnd.github.diff"),
            )
            if diff_resp.status_code != 200:
                raise GitHubServiceError(
                    f"GitHub diff fetch failed: {diff_resp.text}",
                    status_code=diff_resp.status_code,
                )
            diff_text = diff_resp.text

            files = await self._fetch_all_files(client, owner, repo, pull_request_number)

        return PullRequestData(
            number=pr_data["number"],
            title=pr_data.get("title", ""),
            body=pr_data.get("body"),
            html_url=pr_data.get("html_url", ""),
            base_branch=pr_data.get("base", {}).get("ref", "main"),
            head_branch=pr_data.get("head", {}).get("ref", ""),
            state=pr_data.get("state", "open"),
            diff=diff_text,
            files=files,
        )

    async def _fetch_all_files(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        pull_request_number: int,
    ) -> list[dict]:
        files: list[dict] = []
        page = 1
        while True:
            resp = await client.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_request_number}/files",
                headers=self._headers(),
                params={"per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                raise GitHubServiceError(
                    f"GitHub changed-files fetch failed: {resp.text}",
                    status_code=resp.status_code,
                )
            batch = resp.json()
            if not batch:
                break
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files
