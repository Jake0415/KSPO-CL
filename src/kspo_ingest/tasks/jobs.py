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
    # A drained crawl queue is completed even when individual pages/boards warn.
    if int(stats.get("fetched", 0)) == 0 and int(stats.get("errors", 0)) > 0:
        await finish_job(s, job_id, status="FAILED", error="수집된 페이지 없음 — 도메인 도달 실패 또는 차단 추정")
    elif stats.get("termination_reason") == "queue_exhausted" and int(stats.get("pending_urls", -1)) == 0:
        await finish_job(s, job_id, status="SUCCESS")
    elif int(stats.get("processing_failed", 0)) > 0:
        await finish_job(s, job_id, status="FAILED", error="Page post-processing failed")
    elif stats.get("termination_reason") == "url_limit" and int(stats.get("pending_urls", 0)) > 0:
        await finish_job(s, job_id, status="FAILED", error="URL 한도 도달 — 미처리 URL이 남아 있음")
    else:
        # Board limits/fetch errors stay visible in board_outcomes, not job failures.
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


async def locked_job(s: AsyncSession, job_id: int):
    result = await s.execute(
        select(CrawlJob)
        .where(CrawlJob.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def bump_stats(s: AsyncSession, job_id: int, **delta: Any) -> None:
    """Row-lock JSON counters so concurrent page tasks cannot lose increments."""
    job = await locked_job(s, job_id)
    if job is None:
        return
    stats = {**(job.stats or empty_stats())}
    for key, value in delta.items():
        if "__" in key:
            outer, inner = key.split("__", 1)
            sub = dict(stats.get(outer) or {})
            sub[inner] = int(sub.get(inner, 0)) + int(value)
            stats[outer] = sub
        else:
            stats[key] = int(stats.get(key, 0)) + int(value)
    job.stats = stats
    flag_modified(job, "stats")
    await s.commit()


# 컬럼 타입 참조용 (마이그레이션과 일치 검증)
_STATS_TYPE = JSONB
