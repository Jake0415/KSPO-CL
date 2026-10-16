from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from kspo_ingest.api.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_login_locked_after_5_failures(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 5 failed attempts
        for _ in range(5):
            r = await client.post(
                "/api/auth/login",
                data={"username": "admin", "password": "wrong-password"},
            )
            assert r.status_code == 401

        # 6th attempt should be locked (429)
        r = await client.post(
            "/api/auth/login",
            data={"username": "admin", "password": "wrong-password"},
        )
        assert r.status_code == 429
        assert "잠겼습니다" in r.json()["detail"]
