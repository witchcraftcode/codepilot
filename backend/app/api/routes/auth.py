"""Auth API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.github_oauth import AuthService
from app.database.session import get_db
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
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    from app.api.deps import security
    from fastapi import Request

    raise HTTPException(status_code=501, detail="Use Authorization header with /auth/me via deps")
