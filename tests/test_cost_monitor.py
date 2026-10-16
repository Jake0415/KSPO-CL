"""observability/cost_monitor.py 단위 테스트.

- 실제 PG 호출 없이 session.scalar mock으로 cost_usd 합계 결정
- Redis도 mock으로 alert:budget80:YYYYMM 키 동작 검증
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from kspo_ingest.observability import cost_monitor as cm


_KST = ZoneInfo("Asia/Seoul")


def _make_session(*, cost_usd: Decimal | float | int):
    s = MagicMock()
    s.scalar = AsyncMock(return_value=cost_usd)
    return s


def _make_redis(*, exists_returns: int = 0):
    r = MagicMock()
    r.exists = AsyncMock(return_value=exists_returns)
    r.setex = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_zero_usage_returns_zero_krw():
    s = _make_session(cost_usd=0)
    cost = await cm.get_monthly_cost_krw(s)
    assert cost == Decimal("0.00")


@pytest.mark.asyncio
async def test_usd_to_krw_conversion(monkeypatch):
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1370.0)
    s = _make_session(cost_usd=Decimal("0.5"))
    cost = await cm.get_monthly_cost_krw(s)
    # 0.5 * 1370 = 685.00
    assert cost == Decimal("685.00")


@pytest.mark.asyncio
async def test_below_threshold_no_crossed_no_currently_over(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    # 50 USD * 1000 = 50,000 KRW (50%)
    s = _make_session(cost_usd=Decimal("50"))
    redis = _make_redis()

    decision = await cm.check_budget_threshold(s, redis=redis)

    assert decision.cost_krw == Decimal("50000.00")
    assert decision.used_pct == pytest.approx(50.0)
    assert decision.crossed_threshold is False
    assert decision.currently_over is False
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_crossing_sets_redis_and_returns_crossed(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(cost_usd=Decimal("85"))  # 85,000 KRW (85% — over threshold)
    redis = _make_redis(exists_returns=0)  # 아직 발신 안 됨

    decision = await cm.check_budget_threshold(s, redis=redis)

    assert decision.currently_over is True
    assert decision.crossed_threshold is True
    redis.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_already_alerted_same_month_no_re_send(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(cost_usd=Decimal("90"))
    redis = _make_redis(exists_returns=1)  # 이미 발신됨

    decision = await cm.check_budget_threshold(s, redis=redis)

    assert decision.currently_over is True
    assert decision.crossed_threshold is False  # 재발신 X
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_budget_returns_zero_pct_no_alert(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 0)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(cost_usd=Decimal("100"))
    redis = _make_redis()

    decision = await cm.check_budget_threshold(s, redis=redis)

    assert decision.used_pct == 0.0
    assert decision.currently_over is False
    assert decision.crossed_threshold is False


@pytest.mark.asyncio
async def test_no_redis_means_no_dedup_but_still_returns_decision(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(cost_usd=Decimal("85"))

    decision = await cm.check_budget_threshold(s, redis=None)

    assert decision.currently_over is True
    # redis 없으면 crossed_threshold는 False (dedup 보장 불가 — 알림 발신 차단)
    assert decision.crossed_threshold is False


@pytest.mark.asyncio
async def test_first_of_month_kst_returns_kst_first():
    now = datetime(2026, 5, 8, 14, 23, tzinfo=_KST)
    first = cm._first_of_month_kst(now)
    assert first.year == 2026
    assert first.month == 5
    assert first.day == 1
    assert first.hour == 0
    assert first.tzinfo == _KST
