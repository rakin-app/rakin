"""Async SQLAlchemy engine and session factory."""

import asyncpg
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def driver_connection(session: AsyncSession) -> asyncpg.Connection:
    """The asyncpg connection under `session`, inside its transaction: for a request
    that runs code the jobs share, which speaks asyncpg (`app.jobs.billing`)."""
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    driver: asyncpg.Connection = raw.driver_connection
    return driver
