"""GitHub OAuth and JWT authentication."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

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

    def decode_token(self, token: str) -> UUID | None:
        try:
            payload = jwt.decode(token, self.settings.jwt_secret, algorithms=[self.settings.jwt_algorithm])
            return UUID(payload["sub"])
        except (JWTError, ValueError):
            return None

    async def get_github_oauth_url(self) -> str:
        return (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={self.settings.github_client_id}"
            f"&redirect_uri={self.settings.github_redirect_uri}"
            f"&scope=read:user,repo"
        )

    async def handle_github_callback(self, code: str) -> tuple[User, str]:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": self.settings.github_client_id,
                    "client_secret": self.settings.github_client_secret,
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            user_resp = await client.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            gh_user = user_resp.json()

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
