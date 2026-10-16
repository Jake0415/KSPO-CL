"""api/routers/kpi.py 단위 테스트 — /api/kpi/latest + /history."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.api.routers import kpi as kpi_router
from kspo_ingest.observability import kpi as kpi_mod


class FakeSnapshot:
    def __init__(self, **kwargs):
        self.domain_id = kwargs.get("domain_id")
        self.measured_at = kwargs.get("measured_at", datetime.now(UTC))
        self.coverage_pct = kwargs.get("coverage_pct", Decimal("80.00"))
        self.avg_freshness_days = kwargs.get("avg_freshness_days")
        self.job_success_rate_pct = kwargs.get("job_success_rate_pct", Decimal("95.00"))
        self.monthly_cost_krw = kwargs.get("monthly_cost_krw", Decimal("0.00"))
        self.indexed_count = kwargs.get("indexed_count", 0)
        self.dropped_count = kwargs.get("dropped_count", 0)
        self.error_count = kwargs.get("error_count", 0)


def _make_session(*, snapshot=None, history=()):
    s = MagicMock()
    if history:
        rows = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=list(history))
        rows.scalars = MagicMock(return_value=scalars)
        s.execute = AsyncMock(return_value=rows)
    else:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=snapshot)
        s.execute = AsyncMock(return_value=result)
    s.scalar = AsyncMock(return_value=Decimal("0"))
    return s


@pytest.mark.asyncio
async def test_latest_returns_snapshot_when_present():
    snap = FakeSnapshot(domain_id=None, coverage_pct=Decimal("85.00"))
    s = _make_session(snapshot=snap)
    out = await kpi_router.get_latest_kpi(domain_id=None, s=s, _admin="admin")
    assert out.snapshot is True
    assert out.coverage_pct == Decimal("85.00")


@pytest.mark.asyncio
async def test_latest_falls_back_to_measure_when_no_snapshot(monkeypatch):
    s = _make_session(snapshot=None)

    fake = kpi_mod.KpiMeasurement(
        domain_id=None,
        measured_at=datetime.now(UTC),
        coverage_pct=Decimal("0.00"),
        avg_freshness_days=None,
        job_success_rate_pct=Decimal("100.00"),
        monthly_cost_krw=Decimal("0.00"),
        indexed_count=0,
        dropped_count=0,
        error_count=0,
    )

    async def stub_measure(_s, *, domain_id=None, days=7):
        return fake

    monkeypatch.setattr(kpi_router, "measure_kpi", stub_measure)
    out = await kpi_router.get_latest_kpi(domain_id=None, s=s, _admin="admin")
    assert out.snapshot is False
    assert out.coverage_pct == Decimal("0.00")


@pytest.mark.asyncio
async def test_history_returns_list_of_snapshots():
    snaps = [
        FakeSnapshot(coverage_pct=Decimal("80.00")),
        FakeSnapshot(coverage_pct=Decimal("85.00")),
        FakeSnapshot(coverage_pct=Decimal("90.00")),
    ]
    s = _make_session(history=snaps)
    out = await kpi_router.get_kpi_history(domain_id=None, days=30, s=s, _admin="admin")
    assert len(out) == 3
    assert all(o.snapshot is True for o in out)


@pytest.mark.asyncio
async def test_history_empty_returns_empty_list():
    s = _make_session(history=())  # 빈 history
    # _make_session(history=()) → snapshot 분기로 빠짐 — 별도 mock
    rows = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=[])
    rows.scalars = MagicMock(return_value=scalars)
    s.execute = AsyncMock(return_value=rows)

    out = await kpi_router.get_kpi_history(domain_id=42, days=7, s=s, _admin="admin")
    assert out == []


@pytest.mark.asyncio
async def test_latest_with_domain_filter_uses_domain_query():
    snap = FakeSnapshot(domain_id=42)
    s = _make_session(snapshot=snap)
    out = await kpi_router.get_latest_kpi(domain_id=42, s=s, _admin="admin")
    assert out.domain_id == 42


@pytest.mark.asyncio
async def test_kpi_out_serializable():
    snap = FakeSnapshot()
    s = _make_session(snapshot=snap)
    out = await kpi_router.get_latest_kpi(domain_id=None, s=s, _admin="admin")
    payload = out.model_dump()
    assert "coverage_pct" in payload
    assert "snapshot" in payload
