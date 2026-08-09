"""CodePilot AI - FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.api.routes import auth, chat, repository, review
from app.api.routes.evaluation import router as evaluation_router
from app.config import get_settings
from app.database.session import Base, engine
from app.logging_config import REQUEST_ID_HEADER, configure_logging, request_id_ctx
from app.services.cache import cache_service
from app.services.observability import (
    instrument_fastapi,
    prometheus_metrics,
    record_http_request,
    setup_observability,
    system_metrics,
    trace_span,
)
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
    instrument_fastapi(app)

    @app.middleware("http")
    async def add_request_id_and_observability(request: Request, call_next):
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request_id_ctx.set(request_id)
        route_path = request.url.path
        start = time.perf_counter()
        status_code = 500
        try:
            with trace_span("api.request", method=request.method, path=route_path, request_id=request_id):
                response = await call_next(request)
                status_code = response.status_code
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            record_http_request(request.method, route_path, status_code, duration_ms)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(repository.router, prefix=prefix)
    app.include_router(review.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(evaluation_router, prefix=prefix)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/analytics/system")
    async def analytics_system():
        return system_metrics()

    @app.get("/metrics")
    async def metrics():
        content, media_type = prometheus_metrics()
        return Response(content=content, media_type=media_type)

    return app


app = create_app()
