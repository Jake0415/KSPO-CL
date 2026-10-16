"""GET /api/kpi/latest + /api/kpi/history — Admin 대시보드 데이터 소스."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.db.models import KpiSnapshot
from kspo_ingest.observability.kpi import KpiMeasurement, measure_kpi

router = APIRouter(prefix="/api/kpi", tags=["kpi"])


class KpiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    domain_id: int | None = None
    measured_at: datetime
    coverage_pct: Decimal
    avg_freshness_days: Decimal | None = None
    job_success_rate_pct: Decimal
    monthly_cost_krw: Decimal
    indexed_count: int
    dropped_count: int
    error_count: int
    snapshot: bool  # True = DB row, False = on-the-fly measurement


def _from_measurement(m: KpiMeasurement, snapshot: bool) -> KpiOut:
    return KpiOut(
        domain_id=m.domain_id,
        measured_at=m.measured_at,
        coverage_pct=m.coverage_pct,
        avg_freshness_days=m.avg_freshness_days,
        job_success_rate_pct=m.job_success_rate_pct,
        monthly_cost_krw=m.monthly_cost_krw,
        indexed_count=m.indexed_count,
        dropped_count=m.dropped_count,
        error_count=m.error_count,
        snapshot=snapshot,
    )


def _from_snapshot(row: KpiSnapshot) -> KpiOut:
    return KpiOut(
        domain_id=row.domain_id,
        measured_at=row.measured_at,
        coverage_pct=row.coverage_pct,
        avg_freshness_days=row.avg_freshness_days,
        job_success_rate_pct=row.job_success_rate_pct,
        monthly_cost_krw=row.monthly_cost_krw,
        indexed_count=row.indexed_count,
        dropped_count=row.dropped_count,
        error_count=row.error_count,
        snapshot=True,
    )


@router.get("/latest", response_model=KpiOut)
async def get_latest_kpi(
    domain_id: int | None = Query(default=None),
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> KpiOut:
    """가장 최근 snapshot 1행. 없으면 즉시 측정해서 반환(snapshot 저장 안 함)."""
    q = select(KpiSnapshot).order_by(KpiSnapshot.measured_at.desc()).limit(1)
    if domain_id is None:
        q = q.where(KpiSnapshot.domain_id.is_(None))
    else:
        q = q.where(KpiSnapshot.domain_id == domain_id)
    row = (await s.execute(q)).scalar_one_or_none()
    if row is not None:
        return _from_snapshot(row)
    # snapshot 없음 → 즉시 측정 (CronKpi 첫 실행 전이거나 신규 도메인)
    m = await measure_kpi(s, domain_id=domain_id)
    return _from_measurement(m, snapshot=False)


@router.get("/history", response_model=list[KpiOut])
async def get_kpi_history(
    domain_id: int | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> list[KpiOut]:
    since = datetime.now(UTC) - timedelta(days=days)
    q = (
        select(KpiSnapshot)
        .where(KpiSnapshot.measured_at >= since)
        .order_by(KpiSnapshot.measured_at)
    )
    if domain_id is None:
        q = q.where(KpiSnapshot.domain_id.is_(None))
    else:
        q = q.where(KpiSnapshot.domain_id == domain_id)
    rows = (await s.execute(q)).scalars().all()
    return [_from_snapshot(r) for r in rows]
