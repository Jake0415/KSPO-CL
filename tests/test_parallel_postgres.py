"""Explicit opt-in PostgreSQL integration checks; use a disposable database only."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from kspo_ingest.db.models import Base, CrawlJob, Domain, Page
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import bump_stats, finish_crawl_job, locked_job
from kspo_ingest.tasks.pipeline.parallel import (
    drain_processing,
    processing_scope,
    submit_postprocessing,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PARALLEL_PG_TEST") != "1", reason="Disposable PostgreSQL database required"
)


async def setup():
    assert settings.postgres_db.startswith("kspo_parallel_verify_")
    engine = create_async_engine(
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:5432/{settings.postgres_db}",
        pool_size=12,
        max_overflow=8,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        domain = Domain(host=f"{uuid4().hex}.example.org", scheme="https")
        session.add(domain)
        await session.flush()
        job = CrawlJob(domain_id=domain.id, job_type="full", status="RUNNING", stats={})
        session.add(job)
        await session.commit()
    return engine, factory, domain.id, job.id


@pytest.mark.asyncio
async def test_atomic_counters_with_navigation_gauges():
    engine, factory, _, job_id = await setup()
    try:

        async def increment():
            async with factory() as session:
                await bump_stats(session, job_id, refined=1, errors=1, drop_reasons__too_short=1)

        async def gauge():
            async with factory() as session:
                job = await locked_job(session, job_id)
                job.stats = {**job.stats, "pending_urls": 123}
                await session.commit()

        await asyncio.gather(*(increment() for _ in range(60)), *(gauge() for _ in range(20)))
        async with factory() as session:
            job = await session.get(CrawlJob, job_id)
            assert (
                job.stats["refined"]
                == job.stats["errors"]
                == job.stats["drop_reasons"]["too_short"]
                == 60
            )
            assert job.stats["pending_urls"] == 123
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_real_database_pipeline_overlaps_and_drains_before_success():
    engine, factory, domain_id, job_id = await setup()
    try:
        async with factory() as session:
            pages = [
                Page(
                    domain_id=domain_id,
                    url=f"https://test.org/{i}",
                    url_hash=f"{i:040x}",
                    status="CLEANED",
                    storage_paths={"processing_pending": True},
                )
                for i in range(20)
            ]
            session.add_all(pages)
            await session.commit()
        active = peak = 0

        async def work(page_id):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.1)
            async with factory() as session:
                page = await session.get(Page, page_id)
                page.status = "INDEXED"
                await session.commit()
                await bump_stats(session, job_id, refined=1, indexed=1)
            active -= 1

        ctx = {"session_factory": factory, "postprocess_slots": asyncio.BoundedSemaphore(10)}
        async with processing_scope(ctx, job_id) as run:
            for page in pages:
                await submit_postprocessing(run, job_id, page.id, lambda pid=page.id: work(pid))
            await drain_processing(run)
            async with factory() as session:
                await finish_crawl_job(session, job_id)
        async with factory() as session:
            job = await session.get(CrawlJob, job_id)
            assert job.status == "SUCCESS"
            assert (
                job.stats["indexed"]
                == job.stats["refined"]
                == job.stats["processing_completed"]
                == 20
            )
            assert job.stats["processing_pending"] == job.stats["processing_running"] == 0
            rows = (
                (await session.execute(select(Page).where(Page.domain_id == domain_id)))
                .scalars()
                .all()
            )
            assert all(not x.storage_paths["processing_pending"] for x in rows)
        assert 1 < peak <= 10
    finally:
        await engine.dispose()
