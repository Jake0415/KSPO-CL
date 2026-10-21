"""refresh_url — 단건 URL 재처리 ARQ task (M4.T4.2).

흐름: fetch → clean(force 인자 반영) → (skip 또는 refine → push_to_sonar).
extract_links는 호출하지 않음(단건 refresh — 신규 URL 발견 비활성). Frontier 미사용.
"""

from __future__ import annotations

from kspo_ingest.db.models import CrawlJob, Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.gate import upsert_doc_quality
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.tasks.jobs import bump_stats, finish_job, is_cancelled, job_guard, start_job
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.parallel import (
    PublicationError,
    drain_processing,
    processing_scope,
    submit_postprocessing,
)
from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar
from kspo_ingest.tasks.pipeline.refine_page import refine_page

log = get_logger("worker", "refresh_url")


async def refresh_url(ctx: dict, *, job_id: int, page_id: int, force: bool = False) -> None:
    # Any failure must still leave a terminal job status (no ghost RUNNING).
    async with job_guard(ctx["session_factory"], job_id):
        async with ctx["session_factory"]() as session:
            page = await session.get(Page, page_id)
            domain_id = getattr(page, "domain_id", None)
        async with processing_scope(ctx, job_id, domain_id) as run_ctx:
            await _refresh_url_impl(run_ctx, job_id=job_id, page_id=page_id, force=force)


async def _refresh_url_impl(ctx: dict, *, job_id: int, page_id: int, force: bool = False) -> None:
    session_factory = ctx["session_factory"]

    async with session_factory() as s:
        page = await s.get(Page, page_id)
        if page is None:
            await finish_job(s, job_id, status="FAILED", error="page_not_found")
            return
        domain_id = page.domain_id
        url = page.url
        await start_job(s, job_id)

    if await _is_cancelled(session_factory, job_id):
        async with session_factory() as s:
            await finish_job(s, job_id, status="CANCELLED")
        return

    fetched_id = await fetch_page(
        {**ctx, "raise_fetch_errors": True}, job_id=job_id, domain_id=domain_id, url=url, depth=0
    )
    if fetched_id is None:
        # fetch_page가 dropped/error/removed로 stats 처리 — Job은 SUCCESS로 마감
        async with session_factory() as s:
            await _finish_refresh(s, job_id)
        return

    cleaned = await clean_page(ctx, job_id=job_id, page_id=fetched_id, force=force)
    if cleaned is None:
        async with session_factory() as s:
            await _finish_refresh(s, job_id)
        return
    if cleaned.get("skipped"):
        async with session_factory() as s:
            await _finish_refresh(s, job_id)
        log.bind(event="refresh_skip_unchanged", page_id=fetched_id).info("unchanged")
        return

    await submit_postprocessing(
        ctx,
        job_id,
        fetched_id,
        lambda: _finish_page(
            ctx, job_id=job_id, domain_id=domain_id, fetched_id=fetched_id, url=url, cleaned=cleaned
        ),
    )
    await drain_processing(ctx)

    async with session_factory() as s:
        await bump_stats(s, job_id, discovered=1)
        await _finish_refresh(s, job_id)
    log.bind(event="refresh_done", job_id=job_id, page_id=fetched_id, force=force).info(
        "refresh done"
    )


async def _finish_page(
    ctx: dict, *, job_id: int, domain_id: int, fetched_id: int, url: str, cleaned: dict
):
    session_factory = ctx["session_factory"]
    refined = await refine_page(
        ctx,
        job_id=job_id,
        page_id=fetched_id,
        title=cleaned["title"],
        body_text=cleaned["body_text"],
        content_hash=cleaned["content_hash"],
    )
    if refined and refined.get("refined"):
        r = refined["refined"]

        # Quality scoring + quadrant 배정 (enqueue_seeds/board_page와 동일 경로)
        async with session_factory() as s:
            domain = await s.get(Domain, domain_id)
            domain_host = domain.host if domain else ""
            page_row = await s.get(Page, fetched_id)
            page_posted_at = getattr(page_row, "posted_at", None) if page_row else None

        score = score_document(
            ScorerInput(
                title=cleaned["title"],
                body_text=cleaned["body_text"],
                extraction_method=cleaned.get("method", "heuristic"),
                posted_at=page_posted_at,
                summary=r.get("summary"),
                keywords=r.get("keywords") or [],
                is_meaningful=True,
                domain_host=domain_host,
            )
        )

        async with session_factory() as s:
            await upsert_doc_quality(s, page_id=fetched_id, score=score)

        targets = resolve_embedding_targets(score, url=url)
        if targets:
            sent = await push_to_sonar(
                ctx,
                job_id=job_id,
                page_id=fetched_id,
                refined_text=r["refined_text"],
                summary=r.get("summary"),
                keywords=r.get("keywords") or [],
            )
            if sent == 0:
                raise PublicationError(
                    "Sonar publication failed", counted=bool(ctx.get("sonar_client"))
                )


async def _is_cancelled(session_factory, job_id: int) -> bool:
    async with session_factory() as s:
        return await is_cancelled(s, job_id)


async def _finish_refresh(s, job_id: int) -> None:
    """Any processing error means this single URL job failed."""
    job = await s.get(CrawlJob, job_id)
    if job is not None and int((job.stats or {}).get("errors", 0)) > 0:
        await finish_job(s, job_id, status="FAILED", error="URL collection or processing failed")
    else:
        await finish_job(s, job_id, status="SUCCESS")
