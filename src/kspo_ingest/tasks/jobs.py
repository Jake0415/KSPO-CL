"""crawl_jobs 라이프사이클 + stats JSONB 관리.

stats schema (JSONB):
  {
    "discovered": int,   # frontier에 push된 신규
    "fetched":    int,   # HTTP 200으로 응답 받은 페이지 수
    "skipped":    int,   # content_hash 미변경 (incremental — M4)
    "refined":    int,   # LLM 호출 후 성공
    "indexed":    int,   # Qdrant upsert된 청크 수 (M3에서 +1)
    "dropped":    int,   # 사전 룰/not_meaningful로 DROPPED
    "errors":     int,   # 네트워크/추출/임베딩 실패
    "removed":    int,   # orphan REMOVED 전환 (M4)
    "drop_reasons": {"too_short": int, "error_page": int, "non_korean": int, "robots": int},
  }
"""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from kspo_ingest.db.models import CrawlJob

EMPTY_STATS: dict[str, Any] = {
    "discovered": 0,
    "fetched": 0,
    "skipped": 0,
    "refined": 0,
    "indexed": 0,
    "dropped": 0,
    "errors": 0,
    "removed": 0,
    "drop_reasons": {"too_short": 0, "error_page": 0, "non_korean": 0, "robots": 0},
}


def empty_stats() -> dict[str, Any]:
    """매번 새 dict 인스턴스 — JSONB로 PG에 저장될 때 dict shared 참조 방지."""
    return {
        **{k: v for k, v in EMPTY_STATS.items() if k != "drop_reasons"},
        "drop_reasons": dict(EMPTY_STATS["drop_reasons"]),
    }


async def start_job(s: AsyncSession, job_id: int) -> None:
    job = await s.get(CrawlJob, job_id)
    if job is None:
        return
    job.status = "RUNNING"
    job.started_at = datetime.now(UTC)
    await s.commit()


async def finish_job(
    s: AsyncSession, job_id: int, *, status: str, error: str | None = None
) -> None:
    job = await s.get(CrawlJob, job_id)
    if job is None:
        return
    job.status = status
    job.finished_at = datetime.now(UTC)
    if error:
        job.error_message = error
    await s.commit()


async def finish_crawl_job(s: AsyncSession, job_id: int) -> None:
    """stats 기반으로 크롤 잡의 terminal 상태를 확정한다.

    한 페이지도 수집하지 못했는데(fetched==0) 에러가 있으면(errors>0) — 도메인
    도달 실패/차단 등으로 실질적으로 실패한 크롤이므로 FAILED로 표시한다.
    (기존에는 무조건 SUCCESS라 '0건 수집인데 성공'으로 대시보드가 오인시켰다.)
    그 외에는 SUCCESS.
    """
    job = await s.get(CrawlJob, job_id)
    if job is None:
        return
    stats = job.stats or {}
    if int(stats.get("fetched", 0)) == 0 and int(stats.get("errors", 0)) > 0:
        await finish_job(
            s,
            job_id,
            status="FAILED",
            error="수집된 페이지 없음 — 도메인 도달 실패 또는 차단 추정",
        )
    else:
        await finish_job(s, job_id, status="SUCCESS")


@asynccontextmanager
async def job_guard(session_factory, job_id: int):
    """Guarantee a terminal job status on any failure.

    A crawl driver (enqueue_seeds / run_incremental) sets RUNNING and only marks
    SUCCESS/CANCELLED on its normal paths. If the body raises — or the worker is
    killed mid-run — the row would otherwise stay RUNNING forever (audit: 6 ghost
    RUNNING jobs, all-zero stats). This guard marks FAILED and re-raises so ARQ
    retry semantics are preserved. Reusable rule: any long job that writes a
    terminal status must route all exit paths through a guaranteed finalizer.
    """
    try:
        yield
    except BaseException as e:
        # BaseException (not Exception): ARQ job_timeout cancels the task with
        # asyncio.CancelledError (BaseException) — `except Exception` would miss it
        # and leave the job stuck RUNNING. shield() lets the FAILED write commit
        # even while the task is being cancelled.
        msg = str(e)[:500] or type(e).__name__

        async def _mark_failed():
            async with session_factory() as s:
                await finish_job(s, job_id, status="FAILED", error=msg)

        with contextlib.suppress(Exception):
            await asyncio.shield(_mark_failed())
        raise


async def sweep_stale_jobs(s: AsyncSession, older_than_seconds: int) -> int:
    """Mark jobs stuck RUNNING longer than `older_than_seconds` as FAILED.

    Safety net for ghosts that no in-task guard can catch: a hard `kill -9`, an
    OOM, or a container recreate leaves no chance to run job_guard. Called at
    worker startup so a crashed run never lingers as RUNNING forever.
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    # PENDING rows have no started_at → fall back to created_at.
    age_col = func.coalesce(CrawlJob.started_at, CrawlJob.created_at)
    rows = (
        await s.execute(
            select(CrawlJob).where(
                CrawlJob.status.in_(["RUNNING", "PENDING"]),
                age_col < cutoff,
            )
        )
    ).scalars().all()
    for job in rows:
        job.status = "FAILED"
        job.finished_at = datetime.now(UTC)
        job.error_message = "stale job swept at worker startup"
    await s.commit()
    return len(rows)


async def is_cancelled(s: AsyncSession, job_id: int) -> bool:
    """worker가 매 task 시작 시 호출 — True면 task를 즉시 종료."""
    row = (
        await s.execute(select(CrawlJob.status).where(CrawlJob.id == job_id))
    ).scalar_one_or_none()
    return row == "CANCELLED"


async def bump_stats(s: AsyncSession, job_id: int, **delta: Any) -> None:
    """stats JSONB 누계 갱신 — 단일 worker 가정으로 read-modify-write 사용.

    drop_reasons 같은 nested dict 키는 'drop_reasons__too_short=1' 형태로 받음.
    """
    job = await s.get(CrawlJob, job_id)
    if job is None:
        return
    stats = job.stats or empty_stats()

    for key, value in delta.items():
        if "__" in key:
            outer, inner = key.split("__", 1)
            sub = stats.setdefault(outer, {})
            sub[inner] = int(sub.get(inner, 0)) + int(value)
        else:
            stats[key] = int(stats.get(key, 0)) + int(value)

    job.stats = stats
    # SQLAlchemy는 JSONB dict의 in-place mutation(+같은 객체 재할당)을 변경으로
    # 감지하지 못해 커밋해도 저장되지 않는다. flag_modified로 명시적으로 dirty 표시.
    flag_modified(job, "stats")
    s.add(job)
    await s.commit()


# 컬럼 타입 참조용 (마이그레이션과 일치 검증)
_STATS_TYPE = JSONB
