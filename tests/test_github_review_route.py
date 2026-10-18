"""Security and behavior tests for the legacy GitHub PR publishing endpoint."""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.database.session import get_db
from app.github import router as github_router
from app.github.schemas import ReviewComment
from app.main import create_app


class Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDB:
    def __init__(self, repository):
        self.repository = repository

    async def execute(self, statement):
        return Result(self.repository)


def make_client(monkeypatch, user, repository):
    app = create_app()
    db = FakeDB(repository)

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def request_body(repository_id, **updates):
    body = {
        "repository_id": str(repository_id),
        "owner": "acme",
        "repo": "private-repo",
        "pull_number": 3,
    }
    body.update(updates)
    return body


def test_github_review_requires_bearer_auth(monkeypatch):
    repository_id = uuid4()
    user_id = uuid4()
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        full_name="acme/private-repo",
    )
    client = make_client(monkeypatch, None, repository)

    response = client.post("/github/pull-request", json=request_body(repository_id))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner": "../elsewhere"},
        {"repo": "repo/../../users"},
        {"pull_number": 0},
        {"pull_number": -1},
    ],
)
def test_github_review_rejects_malformed_identifiers(monkeypatch, overrides):
    repository_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, access_token="stored-token")
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        full_name="acme/private-repo",
    )
    client = make_client(monkeypatch, user, repository)

    response = client.post(
        "/github/pull-request",
        json=request_body(repository_id, **overrides),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 422


def test_github_review_requires_connected_token_and_repository_access(monkeypatch):
    repository_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, access_token=None)
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        full_name="acme/private-repo",
    )
    client = make_client(monkeypatch, user, repository)
    monkeypatch.setattr(
        github_router,
        "GitHubService",
        lambda **kwargs: pytest.fail("GitHub must not be called without stored authorization"),
    )

    response = client.post(
        "/github/pull-request",
        json=request_body(repository_id, github_token="attacker-token"),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 403
    assert "attacker-token" not in response.text


def test_github_review_rejects_repository_not_owned_by_user(monkeypatch):
    user = SimpleNamespace(id=uuid4(), access_token="stored-token")
    repository_id = uuid4()
    client = make_client(monkeypatch, user, None)

    response = client.post(
        "/github/pull-request",
        json=request_body(repository_id),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 404


def test_github_review_maps_write_permission_failure_without_leaking_tokens(monkeypatch):
    repository_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, access_token="stored-secret-token")
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        full_name="acme/private-repo",
    )

    class ForbiddenGitHub:
        def __init__(self, token):
            assert token == "stored-secret-token"

        async def get_pull_request(self, *args):
            response = httpx.Response(403, request=httpx.Request("GET", "https://api.github.com"))
            raise httpx.HTTPStatusError("forbidden", request=response.request, response=response)

    monkeypatch.setattr(github_router, "GitHubService", ForbiddenGitHub)
    client = make_client(monkeypatch, user, repository)

    response = client.post(
        "/github/pull-request",
        json=request_body(repository_id, github_token="untrusted-body-token"),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 403
    assert "stored-secret-token" not in response.text
    assert "untrusted-body-token" not in response.text


def test_authorized_github_review_publishes_with_stored_token_only(monkeypatch):
    repository_id = uuid4()
    user_id = uuid4()
    user = SimpleNamespace(id=user_id, access_token="stored-secret-token")
    repository = SimpleNamespace(
        id=repository_id,
        owner_id=user_id,
        full_name="acme/private-repo",
    )
    published = []

    class FakeGitHub:
        def __init__(self, token):
            assert token == "stored-secret-token"

        async def get_pull_request(self, owner, repo, pull_number):
            assert (owner, repo, pull_number) == ("acme", "private-repo", 3)
            return {"title": "Change", "user": {"login": "author"}, "head": {"sha": "abc123"}}

        async def get_changed_files(self, *args):
            return [SimpleNamespace(filename="src/app.py", patch="@@ -1 +1 @@")]

        async def get_head_commit(self, *args):
            return "abc123"

        async def create_review(self, **kwargs):
            published.append(kwargs)

    class FakeOrchestrator:
        async def review(self, **kwargs):
            return [
                ReviewComment(
                    file="src/app.py",
                    line=1,
                    severity="medium",
                    category="correctness",
                    message="Potential issue",
                    suggestion="Check the value",
                    confidence=0.8,
                )
            ]

    monkeypatch.setattr(github_router, "GitHubService", FakeGitHub)
    monkeypatch.setattr(github_router, "PullRequestReviewOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        github_router.GitHubCommentMapper,
        "to_github",
        staticmethod(lambda comments: [{"path": "src/app.py", "line": 1, "body": "Finding"}]),
    )
    client = make_client(monkeypatch, user, repository)

    response = client.post(
        "/github/pull-request",
        json=request_body(repository_id, github_token="untrusted-body-token"),
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["files_changed"] == 1
    assert len(published) == 1
    assert published[0]["commit_id"] == "abc123"
    assert "stored-secret-token" not in response.text
    assert "untrusted-body-token" not in response.text
