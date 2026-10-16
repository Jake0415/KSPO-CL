"""get_or_create_page — board_source_id + posted_at 주입 round-trip tests.

PG/alembic 미가용 시 자동 skip (test_board_detect.py와 동일 패턴).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kspo_ingest.db.models import Domain
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pg_reachable() -> bool:
    required = (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    )
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
        ["alembic", "downgrade", "base"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
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
        await s.rollback()
        for tbl in ("board_source", "pages", "crawl_jobs", "domains"):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


@pytest.mark.asyncio
async def test_create_page_with_board_fields(session):
    """신규 페이지 생성 시 posted_at과 board_source_id가 저장된다."""
    d = Domain(host="b.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    dt = datetime(2026, 7, 1, tzinfo=UTC)
    page = await get_or_create_page(
        session, domain_id=d.id, url="https://b.kr/view.do?nttId=1",
        depth=0, board_source_id=None, posted_at=dt,
    )
    assert page.posted_at == dt
    assert page.board_source_id is None


@pytest.mark.asyncio
async def test_existing_page_backfill_posted_at(session):
    """기존 페이지에 posted_at이 없을 때만 보강한다."""
    d = Domain(host="c.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    # 첫 번째 호출 — posted_at 없이 생성
    page1 = await get_or_create_page(
        session, domain_id=d.id, url="https://c.kr/view.do?nttId=2", depth=0,
    )
    assert page1.posted_at is None

    dt = datetime(2026, 7, 2, tzinfo=UTC)
    # 두 번째 호출 — posted_at 보강
    page2 = await get_or_create_page(
        session, domain_id=d.id, url="https://c.kr/view.do?nttId=2", depth=0,
        posted_at=dt,
    )
    assert page2.id == page1.id
    assert page2.posted_at == dt


@pytest.mark.asyncio
async def test_existing_page_does_not_overwrite_posted_at(session):
    """기존 페이지에 posted_at이 이미 있으면 덮어쓰지 않는다."""
    d = Domain(host="d.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    dt_original = datetime(2026, 6, 1, tzinfo=UTC)
    page1 = await get_or_create_page(
        session, domain_id=d.id, url="https://d.kr/view.do?nttId=3", depth=0,
        posted_at=dt_original,
    )
    assert page1.posted_at == dt_original

    dt_new = datetime(2026, 7, 1, tzinfo=UTC)
    page2 = await get_or_create_page(
        session, domain_id=d.id, url="https://d.kr/view.do?nttId=3", depth=0,
        posted_at=dt_new,
    )
    assert page2.id == page1.id
    assert page2.posted_at == dt_original  # 덮어쓰지 않음


@pytest.mark.asyncio
async def test_create_page_with_board_source_id(session):
    """신규 페이지 생성 시 board_source_id가 저장된다."""
    from kspo_ingest.db.models import BoardSource

    d = Domain(host="e.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    bs = BoardSource(domain_id=d.id, list_url="https://e.kr/list.do", status="confirmed")
    session.add(bs)
    await session.commit()
    await session.refresh(bs)

    page = await get_or_create_page(
        session, domain_id=d.id, url="https://e.kr/view.do?nttId=10",
        depth=0, board_source_id=bs.id,
    )
    assert page.board_source_id == bs.id


@pytest.mark.asyncio
async def test_existing_page_does_not_overwrite_board_source_id(session):
    """기존 페이지에 board_source_id가 이미 있으면 덮어쓰지 않는다."""
    from kspo_ingest.db.models import BoardSource

    d = Domain(host="f.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)

    # 두 개의 BoardSource 생성
    bs1 = BoardSource(
        domain_id=d.id,
        list_url="https://f.kr/list1.do",
        status="confirmed",
    )
    session.add(bs1)
    await session.commit()
    await session.refresh(bs1)

    bs2 = BoardSource(
        domain_id=d.id,
        list_url="https://f.kr/list2.do",
        status="confirmed",
    )
    session.add(bs2)
    await session.commit()
    await session.refresh(bs2)

    # 첫 번째 호출 — bs1로 생성
    page1 = await get_or_create_page(
        session,
        domain_id=d.id,
        url="https://f.kr/view.do?nttId=20",
        depth=0,
        board_source_id=bs1.id,
    )
    assert page1.board_source_id == bs1.id

    # 두 번째 호출 — bs2로 시도하지만 덮어쓰지 않음
    page2 = await get_or_create_page(
        session,
        domain_id=d.id,
        url="https://f.kr/view.do?nttId=20",
        depth=0,
        board_source_id=bs2.id,
    )
    assert page2.id == page1.id
    assert page2.board_source_id == bs1.id  # 덮어쓰지 않음
