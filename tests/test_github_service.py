"""Tests for GitHub API service."""

import pytest

from app.services.github_service import GitHubService, GitHubServiceError


class TestGitHubServiceParsing:
    def test_parse_owner_repo_format(self):
        svc = GitHubService()
        owner, repo = svc.parse_repository("octocat/Hello-World")
        assert owner == "octocat"
        assert repo == "Hello-World"

    def test_parse_github_url(self):
        svc = GitHubService()
        owner, repo = svc.parse_repository("https://github.com/fastapi/fastapi")
        assert owner == "fastapi"
        assert repo == "fastapi"

    def test_parse_github_url_with_git_suffix(self):
        svc = GitHubService()
        owner, repo = svc.parse_repository("https://github.com/owner/repo.git")
        assert owner == "owner"
        assert repo == "repo"

    def test_parse_invalid_repository_raises(self):
        svc = GitHubService()
        with pytest.raises(ValueError):
            svc.parse_repository("not-a-valid-repo")


class TestGitHubServiceFetch:
    @pytest.mark.asyncio
    async def test_fetch_public_pull_request(self, monkeypatch):
        svc = GitHubService()

        class FakeResponse:
            def __init__(self, status_code, json_data=None, text=""):
                self.status_code = status_code
                self._json = json_data or {}
                self.text = text

            def json(self):
                return self._json

        pr_json = {
            "number": 42,
            "title": "Add feature",
            "body": "Description here",
            "html_url": "https://github.com/octocat/Hello-World/pull/42",
            "base": {"ref": "main"},
            "head": {"ref": "feature-branch"},
            "state": "open",
        }
        diff_text = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1,2 @@
+x = 1
"""
        files_json = [{"filename": "app.py", "status": "modified", "patch": "@@ -1 +1,2 @@\n+x = 1"}]

        call_count = {"n": 0}

        async def fake_get(self, url, headers=None, params=None):
            call_count["n"] += 1
            if url.endswith("/pulls/42/files"):
                return FakeResponse(200, files_json)
            if headers and headers.get("Accept") == "application/vnd.github.diff":
                return FakeResponse(200, text=diff_text)
            return FakeResponse(200, pr_json)

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            get = fake_get

        monkeypatch.setattr("app.services.github_service.httpx.AsyncClient", lambda **kw: FakeClient())

        result = await svc.fetch_pull_request("octocat", "Hello-World", 42)
        assert result.number == 42
        assert result.title == "Add feature"
        assert "app.py" in result.diff
        assert len(result.files) == 1
        assert call_count["n"] >= 2

    @pytest.mark.asyncio
    async def test_fetch_not_found_raises(self, monkeypatch):
        svc = GitHubService()

        class FakeResponse:
            status_code = 404
            text = "Not Found"

            def json(self):
                return {"message": "Not Found"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, headers=None, params=None):
                return FakeResponse()

        monkeypatch.setattr("app.services.github_service.httpx.AsyncClient", lambda **kw: FakeClient())

        with pytest.raises(GitHubServiceError) as exc_info:
            await svc.fetch_pull_request("octocat", "Missing", 999)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_fetch_private_requires_auth(self, monkeypatch):
        svc = GitHubService()

        class FakeResponse:
            status_code = 401
            text = "Unauthorized"

            def json(self):
                return {"message": "Requires authentication"}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, url, headers=None, params=None):
                return FakeResponse()

        monkeypatch.setattr("app.services.github_service.httpx.AsyncClient", lambda **kw: FakeClient())

        with pytest.raises(GitHubServiceError) as exc_info:
            await svc.fetch_pull_request("private-org", "secret-repo", 1)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_fetch_diff_failure_raises(self, monkeypatch):
        svc = GitHubService()

        class FakeResponse:
            def __init__(self, status_code, json_data=None, text=""):
                self.status_code = status_code
                self._json = json_data or {}
                self.text = text

            def json(self):
                return self._json

        async def fake_get(self, url, headers=None, params=None):
            if headers and headers.get("Accept") == "application/vnd.github.diff":
                return FakeResponse(503, text="diff unavailable")
            return FakeResponse(
                200,
                {
                    "number": 42,
                    "title": "Add feature",
                    "base": {"ref": "main"},
                    "head": {"ref": "feature"},
                    "state": "open",
                },
            )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            get = fake_get

        monkeypatch.setattr("app.services.github_service.httpx.AsyncClient", lambda **kw: FakeClient())

        with pytest.raises(GitHubServiceError) as exc_info:
            await svc.fetch_pull_request("octocat", "Hello-World", 42)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_fetch_files_failure_raises(self, monkeypatch):
        svc = GitHubService()

        class FakeResponse:
            def __init__(self, status_code, json_data=None, text=""):
                self.status_code = status_code
                self._json = json_data or {}
                self.text = text

            def json(self):
                return self._json

        async def fake_get(self, url, headers=None, params=None):
            if url.endswith("/pulls/42/files"):
                return FakeResponse(403, text="rate limited")
            if headers and headers.get("Accept") == "application/vnd.github.diff":
                return FakeResponse(200, text="diff --git a/app.py b/app.py")
            return FakeResponse(
                200,
                {
                    "number": 42,
                    "title": "Add feature",
                    "base": {"ref": "main"},
                    "head": {"ref": "feature"},
                    "state": "open",
                },
            )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            get = fake_get

        monkeypatch.setattr("app.services.github_service.httpx.AsyncClient", lambda **kw: FakeClient())

        with pytest.raises(GitHubServiceError) as exc_info:
            await svc.fetch_pull_request("octocat", "Hello-World", 42)
        assert exc_info.value.status_code == 403

    def test_auth_header_with_token(self):
        svc = GitHubService(access_token="ghp_test_token")
        headers = svc._headers()
        assert headers["Authorization"] == "Bearer ghp_test_token"

    def test_no_auth_header_without_token(self):
        svc = GitHubService(access_token=None)
        headers = svc._headers()
        assert "Authorization" not in headers
