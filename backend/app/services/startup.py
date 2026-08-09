import asyncio
import logging

from qdrant_client import QdrantClient
from sqlalchemy import text

from app.config import get_settings
from app.database.session import engine
from app.services.cache import cache_service

logger = logging.getLogger("codepilot.startup")


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
    settings = get_settings()
    client = QdrantClient(url=settings.qdrant_url)
    try:
        await asyncio.to_thread(client.get_collections)
    except Exception as exc:
        raise RuntimeError("Qdrant connection failure") from exc


async def run_startup_checks() -> None:
    """Run a short health check against each external dependency."""
    logger.info("Performing startup dependency checks")
    await check_postgres_connection()
    await check_redis_connection()
    await check_qdrant_connection()
    logger.info("Startup dependency checks completed successfully")
