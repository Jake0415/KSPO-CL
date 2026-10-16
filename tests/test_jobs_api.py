"""/api/jobs/* 엔드포인트 단위 테스트.

PG/alembic + dependency_overrides로 require_admin 우회.
ARQ pool은 _get_pool monkeypatch로 가짜 풀로 대체 (실 Redis 불필요).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


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


@pytest.fixture(scope="module", autouse=True)
def schema():
    subprocess.run(["alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)
    yield
    subprocess.run(["alembic", "downgrade", "base"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True)


class _FakeArqJob:
    def __init__(self, job_id: str = "fake-arq-1"):
        self.job_id = job_id


class _FakePool:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def enqueue_job(self, fn_name: str, **kwargs):
        self.calls.append((fn_name, kwargs))
        return _FakeArqJob()


@pytest_asyncio.fixture
async def app(monkeypatch):
    """ARQ pool 모킹 + require_admin 우회."""
    from kspo_ingest.api.routers import jobs as jobs_router

    fake = _FakePool()

    async def _fake_get_pool():
        return fake

    monkeypatch.setattr(jobs_router, "_get_pool", _fake_get_pool)

    from kspo_ingest.api.main import create_app

    app = create_app()
    from kspo_ingest.api.deps import require_admin

    app.dependency_overrides[require_admin] = lambda: "test-admin"
    app.state._fake_pool = fake
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def truncate_after(client):
    yield
    from kspo_ingest.db.session import async_session

    async with async_session() as s:
        for tbl in ("llm_usage", "chunks", "attachments", "pages", "crawl_jobs", "domains"):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


async def _create_active_domain(client) -> int:
    r = await client.post("/api/domains", json={"host": "job-api.example.com"})
    assert r.status_code == 201
    return r.json()["id"]


# ---------- POST /api/jobs/full/{id} ----------
async def test_trigger_full_job_creates_pending_job_and_enqueues(client, app):
    domain_id = await _create_active_domain(client)
    r = await client.post(f"/api/jobs/full/{domain_id}")
    assert r.status_code == 201
    body = r.json()
    assert body["domain_id"] == domain_id
    assert body["job_type"] == "full"
    assert body["status"] == "PENDING"
    assert body["arq_job_id"] == "fake-arq-1"
    assert body["stats"]["fetched"] == 0
    # ARQ enqueue 호출 검증
    fake = app.state._fake_pool
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == "enqueue_seeds"
    assert fake.calls[0][1]["domain_id"] == domain_id


async def test_trigger_full_job_404_when_domain_missing(client):
    r = await client.post("/api/jobs/full/99999")
    assert r.status_code == 404


# ---------- GET /api/jobs ----------
async def test_list_jobs_returns_recent_first(client):
    domain_id = await _create_active_domain(client)
    await client.post(f"/api/jobs/full/{domain_id}")
    await client.post(f"/api/jobs/full/{domain_id}")

    r = await client.get("/api/jobs")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2
    # id desc
    assert rows[0]["id"] > rows[1]["id"]


async def test_list_jobs_filter_by_domain(client):
    d1 = await _create_active_domain(client)
    r = await client.post("/api/domains", json={"host": "other-host.example.com"})
    d2 = r.json()["id"]
    await client.post(f"/api/jobs/full/{d1}")
    await client.post(f"/api/jobs/full/{d2}")

    r = await client.get(f"/api/jobs?domain_id={d1}")
    assert r.status_code == 200
    rows = r.json()
    assert all(j["domain_id"] == d1 for j in rows)


# ---------- GET /api/jobs/{id} ----------
async def test_get_job_404(client):
    r = await client.get("/api/jobs/99999")
    assert r.status_code == 404


# ---------- POST /api/jobs/{id}/cancel ----------
async def test_cancel_pending_job(client):
    domain_id = await _create_active_domain(client)
    r = await client.post(f"/api/jobs/full/{domain_id}")
    job_id = r.json()["id"]

    r = await client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 204

    r = await client.get(f"/api/jobs/{job_id}")
    assert r.json()["status"] == "CANCELLED"
    assert r.json()["finished_at"] is not None


# ---------- POST /api/jobs/refresh-url ----------
async def test_refresh_url_existing_page_enqueues(client, app):
    """이미 수집된 URL → refresh_url 큐잉, 도메인 신규생성 아님."""
    from kspo_ingest.crawl.url_normalize import normalize_url
    from kspo_ingest.db.models import Page
    from kspo_ingest.db.session import async_session

    domain_id = await _create_active_domain(client)
    url = "https://job-api.example.com/board/view?id=1"
    normalized, url_hash = normalize_url(url)
    async with async_session() as s:
        s.add(Page(domain_id=domain_id, url=normalized, url_hash=url_hash, status="INDEXED", depth=0))
        await s.commit()

    r = await client.post("/api/jobs/refresh-url", json={"url": url})
    assert r.status_code == 201
    body = r.json()
    assert body["created_domain"] is False
    fake = app.state._fake_pool
    assert fake.calls[-1][0] == "refresh_url"
    assert fake.calls[-1][1]["force"] is False


async def test_refresh_url_new_url_autoregisters_domain_and_page(client, app):
    """한 번도 수집 안 된 신규 도메인 URL → 도메인·페이지 자동 생성 + refresh_url 큐잉."""
    from kspo_ingest.crawl.url_normalize import normalize_url
    from kspo_ingest.db.models import Domain, Page
    from kspo_ingest.db.session import async_session
    from sqlalchemy import select

    url = "https://brand-new-host.example.com/notice/view.do?id=99"
    r = await client.post("/api/jobs/refresh-url", json={"url": url, "force": True})
    assert r.status_code == 201
    body = r.json()
    assert body["created_domain"] is True
    assert body["page_id"] > 0

    _, url_hash = normalize_url(url)
    async with async_session() as s:
        domain = (
            await s.execute(select(Domain).where(Domain.host == "brand-new-host.example.com"))
        ).scalar_one_or_none()
        assert domain is not None and domain.is_active
        page = (
            await s.execute(select(Page).where(Page.url_hash == url_hash))
        ).scalar_one_or_none()
        assert page is not None and page.domain_id == domain.id

    fake = app.state._fake_pool
    assert fake.calls[-1][0] == "refresh_url"
    assert fake.calls[-1][1]["page_id"] == body["page_id"]
    assert fake.calls[-1][1]["force"] is True


async def test_refresh_url_new_url_existing_domain_no_new_domain(client, app):
    """도메인은 있으나 해당 URL은 미수집 → 페이지만 생성, 도메인 신규생성 아님."""
    from kspo_ingest.crawl.url_normalize import normalize_url
    from kspo_ingest.db.models import Page
    from kspo_ingest.db.session import async_session
    from sqlalchemy import select

    await _create_active_domain(client)  # host=job-api.example.com
    url = "https://job-api.example.com/newpost/view.do?id=7"
    r = await client.post("/api/jobs/refresh-url", json={"url": url})
    assert r.status_code == 201
    assert r.json()["created_domain"] is False

    _, url_hash = normalize_url(url)
    async with async_session() as s:
        page = (
            await s.execute(select(Page).where(Page.url_hash == url_hash))
        ).scalar_one_or_none()
        assert page is not None


async def test_cancel_already_finished_job_returns_409(client):
    domain_id = await _create_active_domain(client)
    r = await client.post(f"/api/jobs/full/{domain_id}")
    job_id = r.json()["id"]

    # 직접 SUCCESS로 마감
    from kspo_ingest.db.models import CrawlJob
    from kspo_ingest.db.session import async_session

    async with async_session() as s:
        job = await s.get(CrawlJob, job_id)
        job.status = "SUCCESS"
        await s.commit()

    r = await client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 409
