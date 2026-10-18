import asyncio
import logging

from sqlalchemy import text

from app.config import get_settings
from app.database.session import engine
from app.services.cache import cache_service

logger = logging.getLogger("codepilot.startup")

settings = get_settings()

async def check_postgres_connection() -> None:
    """Verify that PostgreSQL is reachable and accepting queries."""
    logger.debug("Checking PostgreSQL connection")
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:
        # Driver exceptions can include connection details. Log only the class.
        logger.error("startup.check_failed dependency=postgres error_type=%s", type(exc).__name__)
        raise RuntimeError("PostgreSQL startup check failed") from None


async def check_redis_connection() -> None:
    """Verify that Redis is reachable and responding to PING."""
    logger.debug("Checking Redis connection")
    await cache_service.connect()
    ping = await cache_service.client.ping()
    if ping not in (True, "PONG", b"PONG"):
        raise RuntimeError("Redis did not respond to PING")


async def check_qdrant_connection() -> None:
    """Verify the configured Qdrant collection with one bounded async request."""
    logger.debug("Checking Qdrant connection")
    from qdrant_client import AsyncQdrantClient

    timeout_seconds = settings.startup_dependency_timeout_seconds
    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=timeout_seconds,
        check_compatibility=False,
    )
    try:
        # Do not enumerate every collection; readiness requires this collection.
        await client.get_collection(collection_name=settings.qdrant_collection)
    except asyncio.CancelledError:
        logger.info("startup.check_cancelled dependency=qdrant")
        raise
    except Exception as exc:
        logger.error("startup.check_failed dependency=qdrant error_type=%s", type(exc).__name__)
        raise RuntimeError("Qdrant connection failure") from None
    finally:
        try:
            await client.close()
        except Exception as exc:
            logger.warning(
                "startup.client_close_failed dependency=qdrant error_type=%s",
                type(exc).__name__,
            )


async def run_startup_checks() -> None:
    """Run a short health check against each external dependency."""
    logger.info("Performing startup dependency checks")
    checks = (
        ("postgres", check_postgres_connection, settings.database_connect_timeout_seconds + 5),
        ("redis", check_redis_connection, settings.startup_dependency_timeout_seconds),
        # Allow the Qdrant client's own finite request timeout to expire first.
        ("qdrant", check_qdrant_connection, settings.startup_dependency_timeout_seconds + 2),
    )
    for dependency, check, timeout_seconds in checks:
        try:
            await asyncio.wait_for(check(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.error(
                "startup.check_timed_out dependency=%s timeout_seconds=%s",
                dependency,
                timeout_seconds,
            )
            raise RuntimeError(f"Startup dependency check timed out: {dependency}") from None
        except asyncio.CancelledError:
            logger.info("startup.check_cancelled dependency=%s", dependency)
            raise
        except Exception as exc:
            logger.error(
                "startup.check_failed dependency=%s error_type=%s",
                dependency,
                type(exc).__name__,
            )
            raise RuntimeError(f"Startup dependency check failed: {dependency}") from None
    logger.info("Startup dependency checks completed successfully")
