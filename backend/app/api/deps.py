"""FastAPI dependency injection."""

from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.github_oauth import AuthService
from app.database.session import get_db
from app.models.user import User

security = HTTPBearer(auto_error=False)


def _auth_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not credentials:
        raise _auth_error("Not authenticated")
    if credentials.scheme.lower() != "bearer":
        raise _auth_error("Invalid authentication scheme")

    auth = AuthService(db)
    user = await auth.get_current_user(credentials.credentials)
    if not user:
        raise _auth_error("Invalid token")
    return user


async def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User | None:
    if not credentials or credentials.scheme.lower() != "bearer":
        return None
    auth = AuthService(db)
    return await auth.get_current_user(credentials.credentials)
