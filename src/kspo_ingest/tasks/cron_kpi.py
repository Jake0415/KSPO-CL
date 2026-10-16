"""ARQ cron — 매일 KPI snapshot 1+N행 저장 (전체 1 + 활성 도메인별 N).

타이밍 정책:
- 00:30 KST (컨테이너 TZ=Asia/Seoul)
- 증분/전체 크롤(일요일 03:00) + 정기 재시작(둘째 일요일 02:00)과 시간 분리
- 5분 cron(stats_views) / 분당 cron(budget_alerts)와도 충돌 회피
"""
from __future__ import annotations

from sqlalchemy import select

from kspo_ingest.db.models import Domain
from kspo_ingest.observability.kpi import measure_kpi, save_snapshot
from kspo_ingest.observability.logger import get_logger

log = get_logger("cron", "kpi")


async def cron_kpi_daily(ctx: dict) -> dict:
    """전체 KPI 1행 + 활성 도메인별 KPI N행 snapshot 저장.

    Returns: {snapshots_saved: int, domains: int}.
    """
    session_factory = ctx["session_factory"]
    saved = 0

    # 1) 전체 합산
    async with session_factory() as s:
        m_all = await measure_kpi(s, domain_id=None, days=7)
        await save_snapshot(s, m_all)
        saved += 1
        log.bind(
            event="kpi_snapshot_saved",
            scope="all",
            coverage_pct=str(m_all.coverage_pct),
            cost_krw=str(m_all.monthly_cost_krw),
        ).info("kpi snapshot saved (all)")

    # 2) 활성 도메인별
    async with session_factory() as s:
        rows = await s.execute(
            select(Domain).where(Domain.is_active.is_(True))
        )
        domains = list(rows.scalars().all())
    domain_count = len(domains)

    for d in domains:
        async with session_factory() as s:
            m = await measure_kpi(s, domain_id=d.id, days=7)
            await save_snapshot(s, m)
            saved += 1

    log.bind(
        event="kpi_cron_done",
        snapshots_saved=saved,
        domains=domain_count,
    ).info("daily kpi cron done")
    return {"snapshots_saved": saved, "domains": domain_count}
