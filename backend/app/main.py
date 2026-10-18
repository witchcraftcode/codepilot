"""CodePilot AI - FastAPI application entry point."""

import logging
import time
import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.routes import auth, chat, repository, review
from app.api.routes.evaluation import router as evaluation_router
from app.config import get_settings
from app.database.session import AsyncSessionLocal, engine
from app.github.router import router as github_router
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
from app.services.startup import (
    check_postgres_connection,
    check_qdrant_connection,
    check_redis_connection,
    run_startup_checks,
)
from app.services.review_service import ReviewService

logger = logging.getLogger("codepilot.app")


def _request_route_label(request: Request) -> str:
    """Return the matched route template, never a caller supplied identifier."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    return template if isinstance(template, str) else "<unmatched>"


async def _dependencies_ready(
    checks: list[tuple[str, Callable[[], Awaitable[None]]]], timeout_seconds: float
) -> bool:
    for dependency, check in checks:
        try:
            await asyncio.wait_for(check(), timeout=timeout_seconds)
        except Exception:
            logger.warning("readiness.check_failed dependency=%s", dependency)
            return False
    return True


async def _review_recovery_loop() -> None:
    """Periodically fail queued reviews whose in-process task was lost."""
    while True:
        await asyncio.sleep(60)
        try:
            async with AsyncSessionLocal() as session:
                stale_count = await ReviewService.fail_abandoned_pending_reviews(session)
                if stale_count:
                    await session.commit()
                    logger.warning("review.stale_pending_failed count=%d", stale_count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("review.pending_recovery_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    setup_observability()
    logger.info("application.startup")

    await run_startup_checks()
    # Schema lifecycle is managed by Alembic before the service is deployed.
    async with AsyncSessionLocal() as session:
        stale_count = await ReviewService.fail_abandoned_pending_reviews(
            session,
            include_running=True,
        )
        if stale_count:
            await session.commit()
            logger.warning("review.stale_work_failed count=%d", stale_count)

    recovery_task = asyncio.create_task(_review_recovery_loop())
    try:
        yield
    finally:
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
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
        start = time.perf_counter()
        status_code = 500
        try:
            with trace_span("api.request", method=request.method, request_id=request_id):
                response = await call_next(request)
                status_code = response.status_code
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            record_http_request(
                request.method,
                _request_route_label(request),
                status_code,
                duration_ms,
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    prefix = settings.api_prefix
    app.include_router(auth.router, prefix=prefix)
    app.include_router(repository.router, prefix=prefix)
    app.include_router(review.router, prefix=prefix)
    app.include_router(chat.router, prefix=prefix)
    app.include_router(evaluation_router, prefix=prefix)
    app.include_router(github_router)


    @app.get("/")
    async def root():
        return {
            "name": "CodePilot API",
            "status": "healthy",
            "docs": "/docs"
        }

    @app.get("/health")
    async def health():
        """Liveness: process and event loop are responding."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        """Readiness: verify required backing services with bounded checks."""
        checks = [
            ("postgres", check_postgres_connection),
            ("redis", check_redis_connection),
            ("qdrant", check_qdrant_connection),
        ]
        timeout = settings.health_check_timeout_seconds
        if not await _dependencies_ready(checks, timeout):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    @app.get("/analytics/system")
    async def analytics_system():
        return system_metrics()

    @app.get("/metrics")
    async def metrics():
        content, media_type = prometheus_metrics()
        return Response(content=content, media_type=media_type)

    return app


app = create_app()
