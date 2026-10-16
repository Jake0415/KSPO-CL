"""upsert_board_candidate — real-DB round-trip tests.

PG/alembic 미가용 시 자동 skip (test_models_crud.py와 동일 패턴).
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
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kspo_ingest.crawl.board_detect import upsert_board_candidate
from kspo_ingest.db.models import BoardSource, Domain

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
async def test_upsert_creates_confirmed(session):
    d = Domain(host="x.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)
    await upsert_board_candidate(session, domain_id=d.id, list_url="https://x.kr/list.do")
    rows = (await session.execute(BoardSource.__table__.select())).all()
    assert len(rows) == 1
    assert rows[0].status == "confirmed"


@pytest.mark.asyncio
async def test_upsert_idempotent_and_keeps_confirmed(session):
    d = Domain(host="y.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)
    session.add(BoardSource(domain_id=d.id, list_url="https://y.kr/list.do", status="confirmed"))
    await session.commit()
    await upsert_board_candidate(session, domain_id=d.id, list_url="https://y.kr/list.do")
    src = (
        await session.execute(BoardSource.__table__.select().where(BoardSource.domain_id == d.id))
    ).all()
    assert len(src) == 1
    assert src[0].status == "confirmed"  # confirmed 유지


@pytest.mark.asyncio
async def test_upsert_candidate_twice_is_idempotent(session):
    d = Domain(host="z.kr", scheme="https")
    session.add(d)
    await session.commit()
    await session.refresh(d)
    await upsert_board_candidate(session, domain_id=d.id, list_url="https://z.kr/list.do")
    await upsert_board_candidate(session, domain_id=d.id, list_url="https://z.kr/list.do")
    rows = (
        await session.execute(BoardSource.__table__.select().where(BoardSource.domain_id == d.id))
    ).all()
    assert len(rows) == 1
    assert rows[0].status == "confirmed"


@pytest.fixture(autouse=True)
def verified_public_list_response(monkeypatch):
    """DB/API tests use explicit source HTML, never live network responses."""
    from kspo_ingest.crawl.external_fetch import ExternalResult

    html = (
        "<main><table><tr><th>게시일</th></tr>"
        + "".join(
            f'<tr><td><a href="/view.do?nttId={n}">글</a></td><td>2026.10.13</td></tr>'
            for n in (1, 2)
        )
        + "</table></main>"
    )

    async def fetch(url, **kwargs):
        return ExternalResult(200, "text/html;charset=utf-8", html.encode(), url=url)

    monkeypatch.setattr("kspo_ingest.crawl.board_detect.fetch_external", fetch)
