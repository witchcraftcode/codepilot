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
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def check_redis_connection() -> None:
    """Verify that Redis is reachable and responding to PING."""
    logger.debug("Checking Redis connection")
    await cache_service.connect()
    ping = await cache_service.client.ping()
    if ping not in (True, "PONG", b"PONG"):
        raise RuntimeError("Redis did not respond to PING")


async def check_qdrant_connection() -> None:
    """Verify that Qdrant is reachable and accepting requests."""
    logger.debug("Checking Qdrant connection")
    from qdrant_client import QdrantClient

    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=settings.health_check_timeout_seconds,
    )
    try:
        await asyncio.to_thread(client.get_collections)
    except Exception as exc:
        raise RuntimeError("Qdrant connection failure") from exc
    finally:
        client.close()


async def run_startup_checks() -> None:
    """Run a short health check against each external dependency."""
    logger.info("Performing startup dependency checks")
    for check in (
        check_postgres_connection,
        check_redis_connection,
        check_qdrant_connection,
    ):
        await asyncio.wait_for(
            check(),
            timeout=settings.health_check_timeout_seconds,
        )
    logger.info("Startup dependency checks completed successfully")
