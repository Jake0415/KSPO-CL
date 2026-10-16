"""refresh_stats_views cron 단위 테스트 — CONCURRENTLY 정상 + fallback 분기."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.tasks import cron as cron_mod


def _make_session(*, fail_concurrently=False):
    s = MagicMock()
    s.commit = AsyncMock()
    s.rollback = AsyncMock()

    calls: list[str] = []

    async def execute(stmt):
        sql = str(stmt).upper()
        calls.append(sql)
        if "CONCURRENTLY" in sql and fail_concurrently:
            raise RuntimeError("not yet populated")

    s.execute = AsyncMock(side_effect=execute)
    return s, calls


def _make_factory(s):
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=s)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_refresh_concurrently_succeeds_first_try():
    s, calls = _make_session(fail_concurrently=False)
    factory = _make_factory(s)

    result = await cron_mod.refresh_stats_views({"session_factory": factory})

    assert result == {"mode": "concurrently"}
    assert any("CONCURRENTLY" in c for c in calls)
    s.commit.assert_awaited_once()
    s.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_falls_back_to_plain_when_concurrently_fails():
    s, calls = _make_session(fail_concurrently=True)
    factory = _make_factory(s)

    result = await cron_mod.refresh_stats_views({"session_factory": factory})

    assert result == {"mode": "fallback"}
    # CONCURRENTLY 1번 + 일반 REFRESH 1번
    assert sum("CONCURRENTLY" in c for c in calls) == 1
    assert sum("REFRESH MATERIALIZED VIEW" in c and "CONCURRENTLY" not in c for c in calls) == 1
    s.rollback.assert_awaited_once()
    s.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_uses_correct_view_name():
    s, calls = _make_session(fail_concurrently=False)
    factory = _make_factory(s)

    await cron_mod.refresh_stats_views({"session_factory": factory})
    assert all("V_STATS_OVERVIEW" in c for c in calls)


@pytest.mark.asyncio
async def test_refresh_returns_mode_dict():
    s, _ = _make_session(fail_concurrently=False)
    factory = _make_factory(s)
    result = await cron_mod.refresh_stats_views({"session_factory": factory})
    assert isinstance(result, dict)
    assert "mode" in result
