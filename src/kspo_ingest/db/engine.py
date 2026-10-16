from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from kspo_ingest.settings import Settings


def make_engine(s: Settings) -> AsyncEngine:
    dsn = (
        f"postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}"
        f"@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}"
    )
    return create_async_engine(dsn, pool_pre_ping=True, future=True)
