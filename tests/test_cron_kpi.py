"""cron_kpi_daily 단위 테스트 — 전체 1행 + 활성 도메인 N행 snapshot 저장."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.observability import kpi as kpi_mod
from kspo_ingest.tasks import cron_kpi as cron_mod


class FakeDomain:
    def __init__(self, domain_id, host, is_active=True):
        self.id = domain_id
        self.host = host
        self.is_active = is_active


def _make_factory(domains=()):
    """session_factory mock — `select(Domain)` 호출 시 domains 반환."""
    s = MagicMock()
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))

    rows = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(domains))
    rows.scalars = MagicMock(return_value=scalars)
    s.execute = AsyncMock(return_value=rows)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=s)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, s


def _fake_measurement(domain_id):
    return kpi_mod.KpiMeasurement(
        domain_id=domain_id,
        measured_at=datetime.now(UTC),
        coverage_pct=Decimal("80.00"),
        avg_freshness_days=Decimal("3.00"),
        job_success_rate_pct=Decimal("95.00"),
        monthly_cost_krw=Decimal("12345.67"),
        indexed_count=8,
        dropped_count=2,
        error_count=0,
    )


@pytest.mark.asyncio
async def test_zero_domains_saves_only_global_snapshot(monkeypatch):
    factory, _ = _make_factory(domains=[])

    async def fake_measure(_s, *, domain_id=None, days=7):
        return _fake_measurement(domain_id)

    save_calls = []

    async def fake_save(_s, m):
        save_calls.append(m)
        return len(save_calls)

    monkeypatch.setattr(cron_mod, "measure_kpi", fake_measure)
    monkeypatch.setattr(cron_mod, "save_snapshot", fake_save)

    result = await cron_mod.cron_kpi_daily({"session_factory": factory})

    assert result == {"snapshots_saved": 1, "domains": 0}
    assert len(save_calls) == 1
    assert save_calls[0].domain_id is None  # 전체


@pytest.mark.asyncio
async def test_three_domains_saves_one_plus_three(monkeypatch):
    domains = [
        FakeDomain(1, "a.com"),
        FakeDomain(2, "b.com"),
        FakeDomain(3, "c.com"),
    ]
    factory, _ = _make_factory(domains=domains)

    async def fake_measure(_s, *, domain_id=None, days=7):
        return _fake_measurement(domain_id)

    saved_domain_ids = []

    async def fake_save(_s, m):
        saved_domain_ids.append(m.domain_id)
        return len(saved_domain_ids)

    monkeypatch.setattr(cron_mod, "measure_kpi", fake_measure)
    monkeypatch.setattr(cron_mod, "save_snapshot", fake_save)

    result = await cron_mod.cron_kpi_daily({"session_factory": factory})

    assert result == {"snapshots_saved": 4, "domains": 3}
    assert saved_domain_ids == [None, 1, 2, 3]  # 전체 먼저, 그 후 도메인별


@pytest.mark.asyncio
async def test_inactive_domain_query_filters_via_select(monkeypatch):
    """비활성 도메인은 select(Domain).where(is_active=True)에서 자연 제외 — cron는 주는대로 처리."""
    factory, _ = _make_factory(domains=[FakeDomain(1, "a.com")])

    async def fake_measure(_s, *, domain_id=None, days=7):
        return _fake_measurement(domain_id)

    save_calls = []

    async def fake_save(_s, m):
        save_calls.append(m)
        return len(save_calls)

    monkeypatch.setattr(cron_mod, "measure_kpi", fake_measure)
    monkeypatch.setattr(cron_mod, "save_snapshot", fake_save)

    result = await cron_mod.cron_kpi_daily({"session_factory": factory})
    assert result["snapshots_saved"] == 2  # 전체 + 1 도메인


@pytest.mark.asyncio
async def test_returns_dict_for_logging(monkeypatch):
    factory, _ = _make_factory(domains=[])
    monkeypatch.setattr(cron_mod, "measure_kpi", AsyncMock(return_value=_fake_measurement(None)))
    monkeypatch.setattr(cron_mod, "save_snapshot", AsyncMock(return_value=1))

    result = await cron_mod.cron_kpi_daily({"session_factory": factory})
    assert "snapshots_saved" in result
    assert "domains" in result
