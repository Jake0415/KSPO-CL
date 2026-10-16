"""GET /api/settings/env 단위 테스트 — settings 마스킹 검증."""
from __future__ import annotations

import pytest

from kspo_ingest.api.routers import settings_router


@pytest.mark.asyncio
async def test_env_mirror_returns_entries():
    out = await settings_router.get_env_mirror(_admin="admin")
    assert hasattr(out, "entries")
    assert len(out.entries) > 0


@pytest.mark.asyncio
async def test_env_mirror_masks_secret_keys(monkeypatch):
    monkeypatch.setattr(settings_router.settings, "openai_api_key", "sk-real-secret-12345")
    monkeypatch.setattr(settings_router.settings, "smtp_password", "smtp-secret")

    out = await settings_router.get_env_mirror(_admin="admin")
    by_key = {e.key: e for e in out.entries}

    assert by_key["OPENAI_API_KEY"].masked is True
    assert by_key["OPENAI_API_KEY"].value == "***"
    assert by_key["SMTP_PASSWORD"].masked is True


@pytest.mark.asyncio
async def test_env_mirror_keeps_non_secret_in_clear(monkeypatch):
    monkeypatch.setattr(settings_router.settings, "log_level", "DEBUG")
    out = await settings_router.get_env_mirror(_admin="admin")
    by_key = {e.key: e for e in out.entries}
    assert by_key["LOG_LEVEL"].value == "DEBUG"
    assert by_key["LOG_LEVEL"].masked is False


@pytest.mark.asyncio
async def test_env_mirror_secret_empty_value_stays_empty(monkeypatch):
    monkeypatch.setattr(settings_router.settings, "smtp_password", "")
    out = await settings_router.get_env_mirror(_admin="admin")
    by_key = {e.key: e for e in out.entries}
    assert by_key["SMTP_PASSWORD"].value == ""


@pytest.mark.asyncio
async def test_env_mirror_uppercases_keys():
    out = await settings_router.get_env_mirror(_admin="admin")
    for e in out.entries:
        assert e.key == e.key.upper()
