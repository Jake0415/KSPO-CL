"""SQLAlchemy 6 models CRUD round-trip + constraint tests.

PG/alembic 미가용 시 자동 skip.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from kspo_ingest.db.models import Attachment, Chunk, CrawlJob, Domain, LlmUsage, Page


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
    """모듈 시작에 alembic upgrade head, 종료에 downgrade base."""
    subprocess.run(
        ["alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    yield
    subprocess.run(
        ["alembic", "downgrade", "base"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )


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
        # 각 테스트가 만든 데이터 정리 (의존 순서 역순)
        await s.rollback()
        for tbl in ("llm_usage", "chunks", "attachments", "pages", "crawl_jobs", "domains"):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


# ---------- 1) Domain round-trip ----------
async def test_domain_round_trip(session):
    d = Domain(host="www.kspo.or.kr", display_name="KSPO 본사이트")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    assert d.id is not None
    assert d.scheme == "https"
    assert d.max_depth == 10
    assert d.respect_robots is True
    assert d.is_active is True


# ---------- 2) Page UNIQUE constraint ----------
async def test_page_unique_per_domain_url_hash(session):
    d = Domain(host="example1.com")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    p1 = Page(domain_id=d.id, url="https://example1.com/a", url_hash="a" * 40, status="DISCOVERED")
    session.add(p1)
    await session.commit()

    p2 = Page(domain_id=d.id, url="https://example1.com/a", url_hash="a" * 40, status="DISCOVERED")
    session.add(p2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


# ---------- 3) Chunk cascade on attachment delete ----------
async def test_chunk_cascade_on_attachment_delete(session):
    d = Domain(host="cascade.example.com")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    p = Page(domain_id=d.id, url="https://cascade.example.com/p", url_hash="p" * 40, status="INDEXED")
    session.add(p)
    await session.commit()
    await session.refresh(p)

    a = Attachment(
        page_id=p.id,
        domain_id=d.id,
        source_url="https://x/y.pdf",
        file_hash="f" * 64,
        storage_path="/data/x",
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)

    c = Chunk(
        chunk_id_sha1="c" * 40,
        qdrant_point_id=uuid.uuid4(),
        page_id=p.id,
        attachment_id=a.id,
        is_attachment=True,
        chunk_index=0,
        token_len=100,
        embedding_model="text-embedding-3-large",
    )
    session.add(c)
    await session.commit()
    await session.refresh(c)

    chunk_id = c.id

    await session.delete(a)
    await session.commit()

    result = await session.execute(select(Chunk).where(Chunk.id == chunk_id))
    assert result.scalar_one_or_none() is None  # cascade 삭제됨


# ---------- 4) CrawlJob round-trip with JSONB stats ----------
async def test_crawl_job_round_trip(session):
    d = Domain(host="job.example.com")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    job = CrawlJob(
        domain_id=d.id,
        job_type="full",
        status="PENDING",
        stats={"discovered": 0, "fetched": 0, "errors": 0},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    assert job.id is not None
    assert job.triggered_by == "admin"
    assert job.stats == {"discovered": 0, "fetched": 0, "errors": 0}


# ---------- 5) LlmUsage Decimal precision ----------
async def test_llm_usage_decimal_precision(session):
    d = Domain(host="usage.example.com")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    job = CrawlJob(domain_id=d.id, job_type="full", status="RUNNING")
    session.add(job)
    await session.commit()
    await session.refresh(job)

    u = LlmUsage(
        job_id=job.id,
        purpose="refine",
        model="gpt-5.4-mini",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=Decimal("0.123456"),
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)

    assert u.cost_usd == Decimal("0.123456")


# ---------- 6) Attachment UNIQUE on (domain_id, file_hash) ----------
async def test_attachment_unique_per_domain_file_hash(session):
    d = Domain(host="att.example.com")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    p = Page(domain_id=d.id, url="https://att/x", url_hash="x" * 40, status="INDEXED")
    session.add(p)
    await session.commit()
    await session.refresh(p)

    a1 = Attachment(
        page_id=p.id, domain_id=d.id, source_url="https://x/1.pdf",
        file_hash="z" * 64, storage_path="/data/1",
    )
    session.add(a1)
    await session.commit()

    a2 = Attachment(
        page_id=p.id, domain_id=d.id, source_url="https://x/2.pdf",
        file_hash="z" * 64, storage_path="/data/2",
    )
    session.add(a2)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
