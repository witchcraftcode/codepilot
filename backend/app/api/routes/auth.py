"""Auth API routes."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.github_oauth import AuthService
from app.database.session import get_db
from app.models.user import User
from app.schemas import TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
OAUTH_STATE_COOKIE = "codepilot_oauth_state"
OAUTH_STATE_MAX_AGE = 600


@router.get("/github")
async def github_login(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    auth = AuthService(db)
    state, signed_state = auth.create_oauth_state()
    url = await auth.get_github_oauth_url(state)
    settings = auth.settings
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=signed_state,
        max_age=OAUTH_STATE_MAX_AGE,
        httponly=True,
        secure=urlsplit(settings.github_redirect_uri).scheme == "https",
        samesite="lax",
        path=f"{settings.api_prefix}/auth/callback",
    )
    return {"authorization_url": url}


@router.get("/callback", response_model=TokenResponse)
async def github_callback(
    request: Request,
    response: Response,
    code: str = Query(...),
    state: str | None = Query(None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
):
    auth = AuthService(db)
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)

    def clear_state_cookie() -> dict[str, str]:
        response.delete_cookie(
            key=OAUTH_STATE_COOKIE,
            path=f"{auth.settings.api_prefix}/auth/callback",
            httponly=True,
            secure=urlsplit(auth.settings.github_redirect_uri).scheme == "https",
            samesite="lax",
        )
        return {"Set-Cookie": response.headers.get("set-cookie", "")}

    if not auth.validate_oauth_state(cookie_state, state):
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
            headers=clear_state_cookie(),
        )

    try:
        user, token = await auth.handle_github_callback(code)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="GitHub OAuth failed",
            headers=clear_state_cookie(),
        ) from exc
    clear_state_cookie()
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
):
    return user
