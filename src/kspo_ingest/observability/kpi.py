"""KPI 측정 코어 — cron / API / scripts 모두 동일 함수 사용 (단일 진실원).

4 KPI:
1) coverage_pct       — INDEXED / (INDEXED + DROPPED + ERROR)
2) avg_freshness_days — last_indexed_at - discovered_at 평균(일). INDEXED 페이지만.
3) job_success_rate_pct — 최근 N일 SUCCESS / 총 Job
4) monthly_cost_krw   — observability.cost_monitor.get_monthly_cost_krw 위임
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import CrawlJob, KpiSnapshot, Page
from kspo_ingest.observability.cost_monitor import get_monthly_cost_krw


@dataclass
class KpiMeasurement:
    domain_id: int | None
    measured_at: datetime
    coverage_pct: Decimal
    avg_freshness_days: Decimal | None
    job_success_rate_pct: Decimal
    monthly_cost_krw: Decimal
    indexed_count: int
    dropped_count: int
    error_count: int


async def measure_kpi(
    session: AsyncSession,
    *,
    domain_id: int | None = None,
    days: int = 7,
) -> KpiMeasurement:
    """4 KPI 산출. domain_id=None → 전체 합산."""
    indexed, dropped, errored = await _status_counts(session, domain_id)
    total = indexed + dropped + errored
    coverage = (
        (Decimal(indexed) / Decimal(total) * Decimal(100)).quantize(Decimal("0.01"))
        if total > 0
        else Decimal("0.00")
    )

    avg_fresh = await _avg_freshness_days(session, domain_id)
    job_rate = await _job_success_rate(session, domain_id, days)
    monthly_cost = await get_monthly_cost_krw(session)

    return KpiMeasurement(
        domain_id=domain_id,
        measured_at=datetime.now(UTC),
        coverage_pct=coverage,
        avg_freshness_days=avg_fresh,
        job_success_rate_pct=job_rate,
        monthly_cost_krw=monthly_cost,
        indexed_count=indexed,
        dropped_count=dropped,
        error_count=errored,
    )


async def _status_counts(
    session: AsyncSession, domain_id: int | None
) -> tuple[int, int, int]:
    """INDEXED/DROPPED/ERROR 카운트 한 번에. REMOVED 제외."""
    indexed_case = case((Page.status == "INDEXED", 1), else_=0)
    dropped_case = case((Page.status == "DROPPED", 1), else_=0)
    error_case = case((Page.status == "ERROR", 1), else_=0)
    q = select(
        func.coalesce(func.sum(indexed_case), 0),
        func.coalesce(func.sum(dropped_case), 0),
        func.coalesce(func.sum(error_case), 0),
    ).where(Page.status.in_(["INDEXED", "DROPPED", "ERROR"]))
    if domain_id is not None:
        q = q.where(Page.domain_id == domain_id)
    row = (await session.execute(q)).first()
    return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)


async def _avg_freshness_days(
    session: AsyncSession, domain_id: int | None
) -> Decimal | None:
    """평균 (last_indexed_at - discovered_at) — INDEXED 페이지만 (일 단위)."""
    q = select(
        func.avg(
            func.extract("epoch", Page.last_indexed_at)
            - func.extract("epoch", Page.discovered_at)
        )
    ).where(
        Page.status == "INDEXED",
        Page.last_indexed_at.is_not(None),
    )
    if domain_id is not None:
        q = q.where(Page.domain_id == domain_id)
    avg_seconds = await session.scalar(q)
    if avg_seconds is None:
        return None
    return (Decimal(str(avg_seconds)) / Decimal("86400")).quantize(Decimal("0.01"))


async def _job_success_rate(
    session: AsyncSession, domain_id: int | None, days: int
) -> Decimal:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    success_case = case((CrawlJob.status == "SUCCESS", 1), else_=0)
    q = select(
        func.coalesce(func.sum(success_case), 0),
        func.count(),
    ).where(CrawlJob.created_at >= cutoff)
    if domain_id is not None:
        q = q.where(CrawlJob.domain_id == domain_id)
    row = (await session.execute(q)).first()
    success = int(row[0] or 0)
    total = int(row[1] or 0)
    if total == 0:
        return Decimal("100.00")  # 측정 가능한 Job 없으면 100% 가정 (PRD §1.4)
    return (Decimal(success) / Decimal(total) * Decimal(100)).quantize(Decimal("0.01"))


async def save_snapshot(session: AsyncSession, m: KpiMeasurement) -> int:
    snap = KpiSnapshot(
        domain_id=m.domain_id,
        measured_at=m.measured_at,
        coverage_pct=m.coverage_pct,
        avg_freshness_days=m.avg_freshness_days,
        job_success_rate_pct=m.job_success_rate_pct,
        monthly_cost_krw=m.monthly_cost_krw,
        indexed_count=m.indexed_count,
        dropped_count=m.dropped_count,
        error_count=m.error_count,
    )
    session.add(snap)
    await session.commit()
    await session.refresh(snap)
    return snap.id
