"""GET /api/alerts 라우터 단위 테스트.

router 함수를 직접 호출하여 PG/HTTP greenlet 우회. session.scalar mock으로 cost 결정.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.api.routers import alerts as alerts_router
from kspo_ingest.observability import cost_monitor as cm


def _make_session(cost_usd: Decimal):
    s = MagicMock()
    s.scalar = AsyncMock(return_value=cost_usd)
    return s


@pytest.mark.asyncio
async def test_zero_cost_returns_empty_alerts(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(Decimal("0"))

    out = await alerts_router.list_active_alerts(s=s, _admin="admin")
    assert out.alerts == []


@pytest.mark.asyncio
async def test_below_threshold_no_alert(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(Decimal("50"))  # 50,000 KRW = 50%

    out = await alerts_router.list_active_alerts(s=s, _admin="admin")
    assert out.alerts == []


@pytest.mark.asyncio
async def test_above_threshold_returns_budget_80_alert(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(Decimal("85"))  # 85,000 = 85%

    out = await alerts_router.list_active_alerts(s=s, _admin="admin")
    assert len(out.alerts) == 1
    a = out.alerts[0]
    assert a.kind == "budget_80"
    assert a.severity == "warning"
    assert "85.0%" in a.message
    assert a.details["cost_krw"] == "85000.00"


@pytest.mark.asyncio
async def test_alert_response_schema_serializable(monkeypatch):
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)
    s = _make_session(Decimal("90"))

    out = await alerts_router.list_active_alerts(s=s, _admin="admin")
    payload = out.model_dump()
    assert "alerts" in payload
    assert isinstance(payload["alerts"], list)
    assert payload["alerts"][0]["kind"] == "budget_80"


@pytest.mark.asyncio
async def test_alerts_endpoint_does_not_call_redis_setex(monkeypatch):
    """list_active_alerts는 redis=None으로 check_budget_threshold 호출 — alert 발신 차단.
    crossed_threshold 분기는 cron_alerts에서만 실행되어야 한다.
    """
    monkeypatch.setattr(cm.settings, "openai_monthly_budget_krw", 100_000)
    monkeypatch.setattr(cm.settings, "usd_to_krw_rate", 1000.0)

    redis_mock = MagicMock()
    redis_mock.setex = AsyncMock()
    redis_mock.exists = AsyncMock(return_value=0)
    s = _make_session(Decimal("85"))

    await alerts_router.list_active_alerts(s=s, _admin="admin")
    redis_mock.setex.assert_not_awaited()
