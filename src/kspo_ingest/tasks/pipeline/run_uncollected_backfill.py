"""run_uncollected_backfill — 도메인 내 미수집(status=DISCOVERED/ERROR + content_hash NULL)
페이지들을 일괄 처리해 SONAR에 적재.

board_refresh는 confirmed board_source 순회로 리스트 페이지에서 신규 아이템만 발견하므로,
초기 BFS에서 링크만 추출되고 실제 fetch/index가 안 된 URL(예: max_pages 상한 도달, 비-확정
게시판 소속 등)은 잡히지 않는다. 이 태스크는 그 gap을 메우는 backfill.

posted_at 없이 process_board_page 파이프라인을 재사용 — clean/refine 과정에서 HTML
파싱으로 posted_at이 채워질 수 있고, 없으면 None 그대로 진행.
"""

from __future__ import annotations

from sqlalchemy import or_, select

from kspo_ingest.db.models import Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.tasks.jobs import finish_crawl_job, finish_job, is_cancelled, job_guard, start_job
from kspo_ingest.tasks.pipeline.board_page import process_board_page
from kspo_ingest.tasks.pipeline.parallel import (
    drain_processing,
    processing_scope,
)

log = get_logger("worker", "run_uncollected_backfill")


async def run_uncollected_backfill(
    ctx: dict, *, job_id: int, domain_id: int, limit: int = 5000
) -> None:
    async with (
        job_guard(ctx["session_factory"], job_id),
        processing_scope(ctx, job_id, domain_id) as run_ctx,
    ):
        await _run_impl(run_ctx, job_id=job_id, domain_id=domain_id, limit=limit)


async def _run_impl(ctx: dict, *, job_id: int, domain_id: int, limit: int) -> None:
    session_factory = ctx["session_factory"]

    async with session_factory() as s:
        await start_job(s, job_id)
        rows = await s.execute(
            select(Page.id, Page.url, Page.posted_at, Page.board_source_id)
            .where(
                Page.domain_id == domain_id,
                Page.status.in_(("DISCOVERED", "ERROR", "CLEANED", "REFINED")),
                or_(
                    Page.content_hash.is_(None),
                    Page.storage_paths["processing_pending"].as_boolean().is_(True),
                ),
            )
            .limit(limit)
        )
        targets = list(rows.all())

    log.bind(
        event="uncollected_backfill_start",
        job_id=job_id,
        domain_id=domain_id,
        candidates=len(targets),
    ).info("start backfill")

    for _page_id, url, posted_at, board_source_id in targets:
        async with session_factory() as s:
            if await is_cancelled(s, job_id):
                async with session_factory() as s2:
                    await finish_job(s2, job_id, status="CANCELLED")
                return
        try:
            await process_board_page(
                ctx,
                job_id=job_id,
                domain_id=domain_id,
                board_source_id=board_source_id,
                url=url,
                posted_at=posted_at,
            )
        except Exception as exc:
            log.bind(event="uncollected_backfill_error", url=url, err=str(exc)).warning("skip")

    await drain_processing(ctx)
    async with session_factory() as s:
        if not await is_cancelled(s, job_id):
            await finish_crawl_job(s, job_id)
