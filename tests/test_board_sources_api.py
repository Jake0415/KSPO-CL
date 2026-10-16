"""BoardSource CRUD API tests.

PG/alembic 가용 시에만 실행 (로컬에서 SKIP 예상).
test_domains_api.py 패턴을 그대로 따른다.
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


@pytest.fixture(scope="module", autouse=True)
def schema():
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
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
async def app():
    from kspo_ingest.api.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """app.dependency_overrides로 require_admin 우회."""
    from kspo_ingest.api.deps import require_admin

    app.dependency_overrides[require_admin] = lambda: "test-admin"
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def truncate_after(client):
    yield
    from sqlalchemy import text

    from kspo_ingest.db.session import async_session

    async with async_session() as s:
        for tbl in (
            "llm_usage",
            "chunks",
            "attachments",
            "pages",
            "crawl_jobs",
            "board_source",
            "domains",
        ):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


# ---------- auth gating ----------
async def test_unauthed_returns_401(app):
    """인증 미충족 시 401 + WWW-Authenticate: Basic."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/board-sources")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


# ---------- helpers ----------
async def _create_domain(client: AsyncClient) -> int:
    r = await client.post("/api/domains", json={"host": "board.kspo.or.kr"})
    assert r.status_code == 201
    return r.json()["id"]


# ---------- CRUD ----------
async def test_list_empty(client):
    r = await client.get("/api/board-sources")
    assert r.status_code == 200
    assert r.json() == []


async def test_manual_add_returns_confirmed(client):
    did = await _create_domain(client)
    r = await client.post(
        "/api/board-sources", json={"domain_id": did, "list_url": "https://board.kspo.or.kr/list"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["domain_id"] == did


async def test_list_filter_by_status(client):
    did = await _create_domain(client)
    await client.post(
        "/api/board-sources",
        json={"domain_id": did, "list_url": "https://board.kspo.or.kr/list"},
    )
    r = await client.get("/api/board-sources?status=confirmed")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.get("/api/board-sources?status=candidate")
    assert r.status_code == 200
    assert r.json() == []


async def test_confirm_transitions_status(client):

    from kspo_ingest.db.models import BoardSource
    from kspo_ingest.db.session import async_session

    did = await _create_domain(client)
    # Insert a candidate directly in DB
    async with async_session() as s:
        src = BoardSource(domain_id=did, list_url="https://board.kspo.or.kr/candidate")
        s.add(src)
        await s.commit()
        src_id = src.id

    r = await client.post(f"/api/board-sources/{src_id}/confirm")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None


async def test_reject_transitions_status(client):
    from kspo_ingest.db.models import BoardSource
    from kspo_ingest.db.session import async_session

    did = await _create_domain(client)
    async with async_session() as s:
        src = BoardSource(domain_id=did, list_url="https://board.kspo.or.kr/reject-me")
        s.add(src)
        await s.commit()
        src_id = src.id

    r = await client.post(f"/api/board-sources/{src_id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


async def test_delete_returns_204(client):
    did = await _create_domain(client)
    r = await client.post(
        "/api/board-sources", json={"domain_id": did, "list_url": "https://board.kspo.or.kr/del"}
    )
    src_id = r.json()["id"]

    r = await client.delete(f"/api/board-sources/{src_id}")
    assert r.status_code == 204


async def test_confirm_404(client):
    r = await client.post("/api/board-sources/99999/confirm")
    assert r.status_code == 404


async def test_reject_404(client):
    r = await client.post("/api/board-sources/99999/reject")
    assert r.status_code == 404


async def test_delete_404(client):
    r = await client.delete("/api/board-sources/99999")
    assert r.status_code == 404


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


async def test_manual_add_rejects_foreign_and_detail_urls(client):
    did = await _create_domain(client)
    for url in ("https://other.kr/list", "https://board.kspo.or.kr/product/221"):
        response = await client.post("/api/board-sources", json={"domain_id": did, "list_url": url})
        assert response.status_code == 422
    response = await client.get("/api/board-sources")
    assert response.json() == []
