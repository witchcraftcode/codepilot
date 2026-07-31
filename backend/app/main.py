"""CodePilot AI - FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, repository, review
from app.config import get_settings
from app.database.session import Base, engine
from app.logging_config import REQUEST_ID_HEADER, configure_logging, request_id_ctx
from app.services.cache import cache_service
from app.services.observability import setup_observability
from app.services.startup import run_startup_checks

logger = logging.getLogger("codepilot.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    setup_observability()
    logger.info("application.startup")

    await run_startup_checks()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    await cache_service.disconnect()
    await engine.dispose()
    logger.info("application.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request_id_ctx.set(request_id)
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(repository.router, prefix=prefix)
    app.include_router(review.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
