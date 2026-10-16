#!/usr/bin/env python
"""KPI 측정 CLI — observability.kpi.measure_kpi 직접 호출.

사용법:
    python scripts/kpi_measure.py [--domain-id N] [--days 7] [--json]

KPI 4종 정의는 src/kspo_ingest/observability/kpi.py 단일 진실원.
본 스크립트는 측정만 수행하고 snapshot은 저장하지 않음 — daily cron이 담당.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from kspo_ingest.db.session import async_session
from kspo_ingest.observability.kpi import measure_kpi


async def _run_cli(domain_id: int | None, days: int, as_json: bool) -> int:
    async with async_session() as s:
        m = await measure_kpi(s, domain_id=domain_id, days=days)

    if as_json:
        d = asdict(m)
        d["coverage_pct"] = str(d["coverage_pct"])
        d["avg_freshness_days"] = (
            str(d["avg_freshness_days"]) if d["avg_freshness_days"] is not None else None
        )
        d["job_success_rate_pct"] = str(d["job_success_rate_pct"])
        d["monthly_cost_krw"] = str(d["monthly_cost_krw"])
        d["measured_at"] = m.measured_at.isoformat()
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        scope = f"domain_id={domain_id}" if domain_id else "전체 도메인"
        fresh = (
            f"{m.avg_freshness_days}일"
            if m.avg_freshness_days is not None
            else "측정 불가 (INDEXED 페이지 없음)"
        )
        print(f"== KSPO ingest KPI ({scope}, 최근 {days}일) ==")
        print(f"적재 커버리지   : {m.coverage_pct}%")
        print(f"평균 신선도     : {fresh}")
        print(f"Job 성공률      : {m.job_success_rate_pct}%")
        print(f"이번 달 LLM 비용: {m.monthly_cost_krw}원")
        print(
            f"카운트          : INDEXED={m.indexed_count} "
            f"DROPPED={m.dropped_count} ERROR={m.error_count}"
        )
        print(f"측정 시각       : {m.measured_at.isoformat()}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="kspo-ingest KPI 측정")
    p.add_argument("--domain-id", type=int, default=None)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run_cli(args.domain_id, args.days, args.json)))


if __name__ == "__main__":
    main()
