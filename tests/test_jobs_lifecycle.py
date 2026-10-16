"""crawl_jobs 라이프사이클 + stats JSONB merge 테스트.

PG/alembic 미가용 시 자동 skip.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from kspo_ingest.db.models import CrawlJob, Domain
from kspo_ingest.tasks.jobs import (
    bump_stats,
    empty_stats,
    finish_job,
    is_cancelled,
    start_job,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pg_reachable() -> bool:
    required = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    return all(os.getenv(k) for k in required)


def _alembic_available() -> bool:
    return shutil.which("alembic") is not None


pytestmark = pytest.mark.skipif(
    not _pg_reachable() or not _alembic_available(),
    reason="alembic/PG environment not configured",
)


def _async_dsn() -> str:
    return (
        f"postgresql+asyncpg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
        f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
    )


@pytest.fixture(scope="module", autouse=True)
def schema():
    subprocess.run(["alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    yield
    subprocess.run(["alembic", "downgrade", "base"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(_async_dsn(), future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
        await s.rollback()
        for tbl in ("llm_usage", "chunks", "attachments", "pages", "crawl_jobs", "domains"):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


async def _make_job(s: AsyncSession) -> int:
    d = Domain(host="job-life.example.com")
    s.add(d)
    await s.commit()
    await s.refresh(d)

    job = CrawlJob(domain_id=d.id, job_type="full", status="PENDING", stats=empty_stats())
    s.add(job)
    await s.commit()
    await s.refresh(job)
    return job.id


async def test_start_job_sets_running_and_started_at(session):
    job_id = await _make_job(session)
    await start_job(session, job_id)

    job = await session.get(CrawlJob, job_id)
    await session.refresh(job)
    assert job.status == "RUNNING"
    assert job.started_at is not None


async def test_finish_job_success(session):
    job_id = await _make_job(session)
    await start_job(session, job_id)
    await finish_job(session, job_id, status="SUCCESS")

    job = await session.get(CrawlJob, job_id)
    await session.refresh(job)
    assert job.status == "SUCCESS"
    assert job.finished_at is not None
    assert job.error_message is None


async def test_finish_job_failed_with_error_message(session):
    job_id = await _make_job(session)
    await finish_job(session, job_id, status="FAILED", error="boom")
    job = await session.get(CrawlJob, job_id)
    await session.refresh(job)
    assert job.status == "FAILED"
    assert job.error_message == "boom"


async def test_bump_stats_top_level_keys(session):
    job_id = await _make_job(session)
    await bump_stats(session, job_id, fetched=2, errors=1)
    await bump_stats(session, job_id, fetched=3)

    job = await session.get(CrawlJob, job_id)
    await session.refresh(job)
    assert job.stats["fetched"] == 5
    assert job.stats["errors"] == 1


async def test_bump_stats_nested_drop_reasons(session):
    job_id = await _make_job(session)
    await bump_stats(session, job_id, dropped=1, drop_reasons__too_short=1)
    await bump_stats(session, job_id, dropped=2, drop_reasons__too_short=1, drop_reasons__non_korean=1)

    job = await session.get(CrawlJob, job_id)
    await session.refresh(job)
    assert job.stats["dropped"] == 3
    assert job.stats["drop_reasons"]["too_short"] == 2
    assert job.stats["drop_reasons"]["non_korean"] == 1


async def test_is_cancelled_true_after_cancel(session):
    job_id = await _make_job(session)
    assert await is_cancelled(session, job_id) is False

    job = await session.get(CrawlJob, job_id)
    job.status = "CANCELLED"
    await session.commit()

    assert await is_cancelled(session, job_id) is True


async def test_empty_stats_returns_independent_dict_per_call():
    a = empty_stats()
    b = empty_stats()
    a["fetched"] = 99
    a["drop_reasons"]["too_short"] = 5
    assert b["fetched"] == 0
    assert b["drop_reasons"]["too_short"] == 0
