"""Auth API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.github_oauth import AuthService
from app.database.session import get_db
from app.models.user import User
from app.schemas import TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/github")
async def github_login(db: Annotated[AsyncSession, Depends(get_db)]):
    auth = AuthService(db)
    url = await auth.get_github_oauth_url()
    return {"authorization_url": url}


@router.get("/callback", response_model=TokenResponse)
async def github_callback(
    code: str = Query(...),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    auth = AuthService(db)
    try:
        user, token = await auth.handle_github_callback(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth failed: {str(e)}")
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
):
    return user
