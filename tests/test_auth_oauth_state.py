"""OAuth CSRF state validation and callback regression tests."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.api.deps import get_db
from app.auth.github_oauth import AuthService
from app.main import create_app


def make_client():
    app = create_app()

    async def override_db():
        yield object()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_oauth_state_is_signed_and_expires():
    auth = AuthService(None)
    state, cookie_value = auth.create_oauth_state()

    assert auth.validate_oauth_state(cookie_value, state)
    assert not auth.validate_oauth_state(cookie_value, "different-state")
    assert not auth.validate_oauth_state(None, state)
    assert not auth.validate_oauth_state(cookie_value, None)

    expired_cookie = jwt.encode(
        {
            "oauth_state": state,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        auth.settings.jwt_secret,
        algorithm=auth.settings.jwt_algorithm,
    )
    assert not auth.validate_oauth_state(expired_cookie, state)


def test_oauth_login_binds_state_to_http_only_cookie(monkeypatch):
    client = make_client()

    response = client.get("/api/v1/auth/github")

    assert response.status_code == 200
    auth_url = response.json()["authorization_url"]
    state = parse_qs(urlsplit(auth_url).query)["state"][0]
    assert len(state) >= 32
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert client.cookies.get("codepilot_oauth_state")


@pytest.mark.parametrize("state_mode", ["missing_cookie", "mismatch", "missing_query"])
def test_oauth_callback_rejects_invalid_state(monkeypatch, state_mode):
    client = make_client()
    login = client.get("/api/v1/auth/github")
    state = parse_qs(urlsplit(login.json()["authorization_url"]).query)["state"][0]
    if state_mode == "missing_cookie":
        client.cookies.clear()
    elif state_mode == "mismatch":
        state = "attacker-state"

    params = {"code": "fake-code"}
    if state_mode != "missing_query":
        params["state"] = state
    response = client.get("/api/v1/auth/callback", params=params)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired OAuth state"
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_oauth_callback_success_consumes_state(monkeypatch):
    client = make_client()

    async def complete_callback(self, code):
        assert code == "fake-code"
        return (
            SimpleNamespace(
                id=uuid4(),
                username="octocat",
                email=None,
                avatar_url=None,
            ),
            "access-jwt",
        )

    monkeypatch.setattr(AuthService, "handle_github_callback", complete_callback)
    login = client.get("/api/v1/auth/github")
    state = parse_qs(urlsplit(login.json()["authorization_url"]).query)["state"][0]

    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "fake-code", "state": state},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "access-jwt"
    assert "max-age=0" in response.headers["set-cookie"].lower()
    replay = client.get(
        "/api/v1/auth/callback",
        params={"code": "fake-code", "state": state},
    )
    assert replay.status_code == 400


def test_oauth_callback_failure_hides_provider_exception(monkeypatch):
    client = make_client()

    async def fail_callback(self, code):
        raise RuntimeError("provider-secret-details")

    monkeypatch.setattr(AuthService, "handle_github_callback", fail_callback)
    login = client.get("/api/v1/auth/github")
    state = parse_qs(urlsplit(login.json()["authorization_url"]).query)["state"][0]

    response = client.get(
        "/api/v1/auth/callback",
        params={"code": "fake-code", "state": state},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "GitHub OAuth failed"
    assert "provider-secret-details" not in response.text
    assert "max-age=0" in response.headers["set-cookie"].lower()
