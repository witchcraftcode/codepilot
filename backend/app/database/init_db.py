"""Initialize PostgreSQL tables."""

import asyncio

from app.database.session import engine
from app.models import *


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("Database initialized successfully.")


if __name__ == "__main__":
    asyncio.run(init())