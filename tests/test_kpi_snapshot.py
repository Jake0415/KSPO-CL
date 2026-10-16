"""observability/kpi.py — measure_kpi + save_snapshot 단위 테스트.

session.execute / scalar mock으로 SQL 분기 검증. 실제 PG 호출 없음.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.observability import cost_monitor as cm
from kspo_ingest.observability import kpi as kpi_mod


def _row(*values):
    r = MagicMock()
    r.first = MagicMock(return_value=values)
    return r


@pytest.fixture
def fake_cost(monkeypatch):
    async def _stub(_s, *, now=None):
        return Decimal("12345.67")

    monkeypatch.setattr(cm, "get_monthly_cost_krw", _stub)
    monkeypatch.setattr(kpi_mod, "get_monthly_cost_krw", _stub)


@pytest.mark.asyncio
async def test_zero_pages_zero_jobs(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(0, 0, 0), _row(0, 0)])
    s.scalar = AsyncMock(return_value=None)

    m = await kpi_mod.measure_kpi(s)
    assert m.coverage_pct == Decimal("0.00")
    assert m.avg_freshness_days is None
    assert m.job_success_rate_pct == Decimal("100.00")  # 측정 가능 Job 0 → 100% (PRD §1.4)
    assert m.indexed_count == m.dropped_count == m.error_count == 0


@pytest.mark.asyncio
async def test_indexed_8_dropped_2_error_0_coverage_80(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(8, 2, 0), _row(0, 0)])
    s.scalar = AsyncMock(return_value=None)
    m = await kpi_mod.measure_kpi(s)
    assert m.coverage_pct == Decimal("80.00")
    assert m.indexed_count == 8


@pytest.mark.asyncio
async def test_freshness_seconds_to_days_quantized(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(5, 0, 0), _row(0, 0)])
    s.scalar = AsyncMock(return_value=86_400.0 * 3)  # 3일
    m = await kpi_mod.measure_kpi(s)
    assert m.avg_freshness_days == Decimal("3.00")


@pytest.mark.asyncio
async def test_job_success_rate_9_of_10(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(0, 0, 0), _row(9, 10)])
    s.scalar = AsyncMock(return_value=None)
    m = await kpi_mod.measure_kpi(s, days=14)
    assert m.job_success_rate_pct == Decimal("90.00")


@pytest.mark.asyncio
async def test_domain_id_is_passed_through(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(1, 0, 0), _row(1, 1)])
    s.scalar = AsyncMock(return_value=None)
    m = await kpi_mod.measure_kpi(s, domain_id=42)
    assert m.domain_id == 42


@pytest.mark.asyncio
async def test_save_snapshot_creates_row(fake_cost):
    s = MagicMock()
    s.add = MagicMock()
    s.commit = AsyncMock()

    async def _refresh(obj):
        obj.id = 999

    s.refresh = AsyncMock(side_effect=_refresh)

    m = kpi_mod.KpiMeasurement(
        domain_id=None,
        measured_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        coverage_pct=Decimal("80.00"),
        avg_freshness_days=Decimal("3.00"),
        job_success_rate_pct=Decimal("95.00"),
        monthly_cost_krw=Decimal("12345.67"),
        indexed_count=8,
        dropped_count=2,
        error_count=0,
    )
    snap_id = await kpi_mod.save_snapshot(s, m)
    assert snap_id == 999
    s.add.assert_called_once()
    s.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_monthly_cost_propagates_to_measurement(fake_cost):
    s = MagicMock()
    s.execute = AsyncMock(side_effect=[_row(0, 0, 0), _row(0, 0)])
    s.scalar = AsyncMock(return_value=None)
    m = await kpi_mod.measure_kpi(s)
    assert m.monthly_cost_krw == Decimal("12345.67")
