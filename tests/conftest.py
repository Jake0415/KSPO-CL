from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient


# Set required env vars BEFORE importing the app
os.environ.setdefault("ADMIN_PASSWORD_BCRYPT", "$2b$12$placeholder0000000000000000000000000000000000000000")
os.environ.setdefault("SESSION_SECRET", "ci_dummy_session_secret_at_least_32_bytes_long")
os.environ.setdefault("POSTGRES_USER", "kspo")
os.environ.setdefault("POSTGRES_PASSWORD", "kspo")


@pytest.fixture(autouse=True)
def _reset_lockout_state():
    """Reset login lockout singleton between tests to prevent cross-test pollution."""
    yield
    try:
        from kspo_ingest.api.routers import auth as _auth_mod
        if hasattr(_auth_mod, "_lockout"):
            _auth_mod._lockout._state.clear()
    except Exception:
        pass


@pytest.fixture
async def client():
    from kspo_ingest.api.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
