import httpx
from typing import List

from .schemas import ChangedFile

GITHUB_API = "https://api.github.com"


class GitHubService:
    def __init__(self, token: str | None = None):
        self.token = token

    def _headers(self):
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        return headers

    async def get_pull_request(self, owner: str, repo: str, pr: int):
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers())

        response.raise_for_status()
        return response.json()

    async def get_head_commit(
        self,
        owner: str,
        repo: str,
        pr: int,
    ) -> str:
        """
        Returns the latest head commit SHA for the pull request.
        """

        pr_data = await self.get_pull_request(owner, repo, pr)
        return pr_data["head"]["sha"]

    async def get_changed_files(
        self,
        owner: str,
        repo: str,
        pr: int,
    ) -> List[ChangedFile]:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr}/files"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self._headers())

        response.raise_for_status()

        files = []
        for item in response.json():
            files.append(
                ChangedFile(
                    filename=item["filename"],
                    status=item["status"],
                    additions=item["additions"],
                    deletions=item["deletions"],
                    changes=item["changes"],
                    patch=item.get("patch"),
                )
            )

        return files

    async def create_review(
        self,
        owner: str,
        repo: str,
        pr: int,
        commit_id: str,
        comments: list[dict],
        body: str = "🤖 CodePilot AI Review",
    ):
        """
        Publish an inline GitHub Pull Request review.
        """

        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr}/reviews"

        payload = {
            "commit_id": commit_id,
            "event": "COMMENT",
            "body": body,
            "comments": comments,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json=payload,
            )

        response.raise_for_status()
        return response.json()