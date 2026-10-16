"""Domain CRUD API tests.

T1.4 머지 전 fail-safe 검증 1건 + dependency_overrides로 우회한 CRUD 6건.
PG/alembic 가용 시에만 실행.
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
    subprocess.run(
        ["alembic", "upgrade", "head"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )
    yield
    subprocess.run(
        ["alembic", "downgrade", "base"], cwd=PROJECT_ROOT, check=True, capture_output=True, text=True
    )


@pytest_asyncio.fixture
async def app():
    from kspo_ingest.api.main import create_app

    return create_app()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """app.dependency_overrides로 require_admin 우회 — T1.4 머지 후엔 실 인증 사용."""
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
    # 매 테스트 후 도메인·하위 테이블 정리
    from sqlalchemy import text

    from kspo_ingest.db.session import async_session

    async with async_session() as s:
        for tbl in ("llm_usage", "chunks", "attachments", "pages", "crawl_jobs", "domains"):
            await s.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
        await s.commit()


# ---------- auth gating (T1.4 머지 후) ----------
async def test_unauthed_returns_401(app):
    """인증 미충족 시 401 + WWW-Authenticate: Basic."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/domains")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


# ---------- CRUD ----------
async def test_list_empty(client):
    r = await client.get("/api/domains")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_get_delete_round_trip(client):
    r = await client.post("/api/domains", json={"host": "www.kspo.or.kr", "display_name": "KSPO"})
    assert r.status_code == 201
    body = r.json()
    did = body["id"]
    assert body["host"] == "www.kspo.or.kr"
    assert body["scheme"] == "https"
    assert body["max_depth"] == 10

    r = await client.get(f"/api/domains/{did}")
    assert r.status_code == 200
    assert r.json()["host"] == "www.kspo.or.kr"

    r = await client.delete(f"/api/domains/{did}")
    assert r.status_code == 204

    r = await client.get(f"/api/domains/{did}")
    assert r.status_code == 404


async def test_create_duplicate_host_returns_409(client):
    payload = {"host": "dup.example.com"}
    r1 = await client.post("/api/domains", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/domains", json=payload)
    assert r2.status_code == 409


async def test_patch_partial_update(client):
    r = await client.post("/api/domains", json={"host": "patch.example.com"})
    did = r.json()["id"]

    r = await client.patch(f"/api/domains/{did}", json={"max_depth": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["max_depth"] == 3
    # 다른 필드는 유지
    assert body["max_pages"] == 20_000
    assert body["host"] == "patch.example.com"


async def test_patch_extra_field_rejected(client):
    r = await client.post("/api/domains", json={"host": "extra.example.com"})
    did = r.json()["id"]
    # extra=forbid: 모르는 필드는 422
    r = await client.patch(f"/api/domains/{did}", json={"unknown_field": 1})
    assert r.status_code == 422


async def test_invalid_host_with_scheme_rejected(client):
    r = await client.post("/api/domains", json={"host": "https://example.com"})
    assert r.status_code == 422


async def test_get_404(client):
    r = await client.get("/api/domains/99999")
    assert r.status_code == 404


async def test_host_lowercased_and_trimmed(client):
    r = await client.post("/api/domains", json={"host": "  WWW.KSPO.or.KR  "})
    assert r.status_code == 201
    assert r.json()["host"] == "www.kspo.or.kr"
