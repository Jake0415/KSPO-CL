"""Admin auth tests — Basic→session, fallback, 화이트리스트.

PG/alembic 미가용 시 일부 테스트 skip (대부분은 PG 불필요).
"""
from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
import bcrypt


ADMIN_USER = "admin"
ADMIN_PW = "secret123"
ADMIN_HASH = bcrypt.hashpw(ADMIN_PW.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("ascii")  # 테스트는 cost 4로 빠르게


@pytest.fixture(autouse=True)
def configured_env(monkeypatch):
    """settings 객체는 module-load 시점에 인스턴스화되므로 env 패치 + reload."""
    monkeypatch.setenv("ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("ADMIN_PASSWORD_BCRYPT", ADMIN_HASH)
    monkeypatch.setenv("SESSION_SECRET", "x" * 48)
    monkeypatch.setenv("SESSION_MAX_AGE_SECONDS", "28800")
    monkeypatch.setenv("POSTGRES_USER", os.getenv("POSTGRES_USER", "kspo"))
    monkeypatch.setenv("POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", "kspo"))

    # settings 모듈 reload (이미 import된 경우 새 환경변수가 반영되도록)
    import importlib

    from kspo_ingest import settings as settings_mod

    importlib.reload(settings_mod)
    # deps / auth / password 모듈도 reload — settings 참조 갱신
    from kspo_ingest.api.auth import password as password_mod
    from kspo_ingest.api.auth import session as session_mod
    from kspo_ingest.api.routers import auth as auth_router_mod
    from kspo_ingest.api import deps as deps_mod

    importlib.reload(password_mod)
    importlib.reload(session_mod)
    importlib.reload(auth_router_mod)
    importlib.reload(deps_mod)
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # configured_env가 reload한 후에 main을 import해야 새 settings·deps 반영
    import importlib

    from kspo_ingest.api import main as main_mod

    importlib.reload(main_mod)
    app = main_mod.create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------- 화이트리스트 ----------
async def test_healthz_no_auth_required(client):
    r = await client.get("/healthz")
    assert r.status_code == 200


async def test_docs_no_auth_required(client):
    r = await client.get("/docs")
    assert r.status_code == 200


# ---------- 미인증 ----------
async def test_protected_without_session_returns_401(client):
    r = await client.get("/api/domains")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate", "").lower().startswith("basic")


async def test_me_without_credentials_returns_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


# ---------- 로그인 / 세션 ----------
async def test_login_sets_session_cookie(client):
    r = await client.post(
        "/api/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PW},
    )
    assert r.status_code == 200
    assert r.json()["username"] == ADMIN_USER
    assert "session" in r.cookies


async def test_login_wrong_password_returns_401(client):
    r = await client.post(
        "/api/auth/login",
        data={"username": ADMIN_USER, "password": "wrong"},
    )
    assert r.status_code == 401


async def test_login_wrong_username_returns_401(client):
    r = await client.post(
        "/api/auth/login",
        data={"username": "intruder", "password": ADMIN_PW},
    )
    assert r.status_code == 401


async def test_me_after_login_returns_session_user(client):
    await client.post(
        "/api/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PW},
    )
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == ADMIN_USER
    assert body["via"] == "session"


async def test_logout_clears_session(client):
    await client.post(
        "/api/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PW},
    )
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204

    r = await client.get("/api/auth/me")
    assert r.status_code == 401


# ---------- Basic fallback ----------
async def test_basic_fallback_works_on_me(client):
    creds = base64.b64encode(f"{ADMIN_USER}:{ADMIN_PW}".encode()).decode()
    r = await client.get("/api/auth/me", headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 200
    body = r.json()
    assert body["via"] == "basic"


async def test_basic_fallback_wrong_pw(client):
    creds = base64.b64encode(f"{ADMIN_USER}:wrong".encode()).decode()
    r = await client.get("/api/auth/me", headers={"Authorization": f"Basic {creds}"})
    assert r.status_code == 401
