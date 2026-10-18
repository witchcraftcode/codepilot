"""GitHub OAuth and JWT authentication."""

from datetime import datetime, timedelta, timezone
import secrets
from uuid import UUID
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.user import User


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    def create_access_token(self, user_id: UUID) -> str:
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.settings.jwt_expire_minutes)
        payload = {"sub": str(user_id), "exp": expire}
        return jwt.encode(payload, self.settings.jwt_secret, algorithm=self.settings.jwt_algorithm)

    def create_oauth_state(self) -> tuple[str, str]:
        """Create a browser-bound nonce and its signed, short-lived cookie value."""
        state = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        cookie = jwt.encode(
            {"oauth_state": state, "exp": expires_at},
            self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )
        return state, cookie

    def validate_oauth_state(self, cookie: str | None, returned_state: str | None) -> bool:
        if not cookie or not returned_state:
            return False
        try:
            payload = jwt.decode(
                cookie,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
            expected = payload.get("oauth_state")
            return isinstance(expected, str) and secrets.compare_digest(
                expected, returned_state
            )
        except (JWTError, TypeError, ValueError):
            return False

    def decode_token(self, token: str) -> UUID | None:
        try:
            payload = jwt.decode(token, self.settings.jwt_secret, algorithms=[self.settings.jwt_algorithm])
            return UUID(payload["sub"])
        except (JWTError, KeyError, TypeError, ValueError):
            return None

    async def get_github_oauth_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.settings.github_client_id,
                "redirect_uri": self.settings.github_redirect_uri,
                "scope": "read:user,repo",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{query}"

    async def handle_github_callback(self, code: str) -> tuple[User, str]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("GitHub did not issue an access token")

            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_resp.raise_for_status()
            gh_user = user_resp.json()

        if not isinstance(gh_user, dict) or not gh_user.get("id") or not gh_user.get("login"):
            raise ValueError("GitHub returned an invalid user profile")

        result = await self.db.execute(select(User).where(User.github_id == gh_user["id"]))
        user = result.scalar_one_or_none()

        if user:
            user.access_token = access_token
            user.avatar_url = gh_user.get("avatar_url")
        else:
            user = User(
                github_id=gh_user["id"],
                username=gh_user["login"],
                email=gh_user.get("email"),
                avatar_url=gh_user.get("avatar_url"),
                access_token=access_token,
            )
            self.db.add(user)

        await self.db.flush()
        token = self.create_access_token(user.id)
        return user, token

    async def get_current_user(self, token: str) -> User | None:
        user_id = self.decode_token(token)
        if not user_id:
            return None
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
