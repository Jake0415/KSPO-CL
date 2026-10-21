from __future__ import annotations

import base64
import json

import pytest
from httpx import ASGITransport, AsyncClient
from itsdangerous import TimestampSigner

from kspo_ingest.api import main
from kspo_ingest.api.auth import session
from kspo_ingest.api.routers import auth


@pytest.mark.asyncio
@pytest.mark.parametrize("max_age, expected", [(0, 200), (28800, 401)])
async def test_old_cookie_and_login_timestamp_follow_expiry_setting(monkeypatch, max_age, expected):
    monkeypatch.setattr(main.settings, "session_max_age_seconds", max_age)
    monkeypatch.setattr(session.settings, "session_max_age_seconds", max_age)
    monkeypatch.setattr(main.settings, "app_env", "local")
    monkeypatch.setattr(auth, "verify_password", lambda password: True)
    app = main.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login",
            data={"username": auth.settings.admin_username, "password": "test-only-password"},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert ("max-age=" in cookie) == bool(max_age)
        assert "httponly" in cookie and "samesite=lax" in cookie
        signer = TimestampSigner(main.settings.session_secret)
        data = json.loads(base64.b64decode(signer.unsign(response.cookies["session"])))
        data["admin"]["iat"] = 1
        encoded = base64.b64encode(json.dumps(data).encode())
        with monkeypatch.context() as old_time:
            old_time.setattr(TimestampSigner, "get_timestamp", lambda self: 1)
            old_cookie = signer.sign(encoded).decode()
        client.cookies.clear()
        client.cookies.set("session", old_cookie, domain="test.local", path="/")
        response = await client.get("/api/auth/me")
        assert response.status_code == expected
        if not max_age:
            response = await client.post("/api/auth/logout")
            assert response.status_code == 204
            assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_application_timestamp_still_expires_with_fresh_signature(monkeypatch):
    monkeypatch.setattr(main.settings, "session_max_age_seconds", 28800)
    monkeypatch.setattr(session.settings, "session_max_age_seconds", 28800)
    monkeypatch.setattr(main.settings, "app_env", "local")
    data = {"admin": {"u": "admin", "iat": 1}}
    token = (
        TimestampSigner(main.settings.session_secret)
        .sign(base64.b64encode(json.dumps(data).encode()))
        .decode()
    )
    async with AsyncClient(
        transport=ASGITransport(app=main.create_app()), base_url="http://test"
    ) as client:
        client.cookies.set("session", token, domain="test.local", path="/")
        assert (await client.get("/api/auth/me")).status_code == 401
