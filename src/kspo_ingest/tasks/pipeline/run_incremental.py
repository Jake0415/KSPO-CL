"""run_incremental — incremental Job 진입점.

흐름:
  1. start_job(RUNNING)
  2. 도메인의 기존 페이지(REMOVED 제외) URL 목록 + 도메인 root URL 수집
  3. 각 URL에 대해 fetch → clean → (skipped면 skip) refine → chunk_and_index 체인 inline 실행
     - 404는 fetch_page가 handle_404 호출 (orphan.py) — REMOVED 전환 처리
     - content_hash 미변경은 clean_page에서 SKIPPED 분기
     - LLM 의미 판단은 제외 조건으로 사용하지 않음
  4. finish_job(SUCCESS)

NOTE: 본 task는 frontier 기반 BFS를 도입하지 않는다 (M2와 동일 inline 모델 유지).
신규 URL 발견은 root URL 재크롤로만 — 사이트 내 link extract는 후속 task.
"""

from __future__ import annotations

from sqlalchemy import select

from kspo_ingest.crawl.board import classify_freshness
from kspo_ingest.crawl.soma import is_board_article
from kspo_ingest.db.models import CrawlJob, Domain, Page
from kspo_ingest.observability.cost_monitor import is_budget_exceeded
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.gate import upsert_doc_quality
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import (
    bump_stats,
    finish_crawl_job,
    finish_job,
    is_cancelled,
    job_guard,
    start_job,
)
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.extract_links import extract_links
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.helpers import mark_dropped
from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar
from kspo_ingest.tasks.pipeline.refine_page import refine_page

log = get_logger("worker", "run_incremental")


async def run_incremental(ctx: dict, *, job_id: int, domain_id: int) -> None:
    # Any failure in the incremental body must still leave a terminal job status.
    async with job_guard(ctx["session_factory"], job_id):
        await _run_incremental_impl(ctx, job_id=job_id, domain_id=domain_id)


async def _run_incremental_impl(ctx: dict, *, job_id: int, domain_id: int) -> None:
    session_factory = ctx["session_factory"]

    async with session_factory() as s:
        domain = await s.get(Domain, domain_id)
        if domain is None:
            await finish_job(s, job_id, status="FAILED", error="domain_not_found")
            return
        if not domain.is_active:
            await finish_job(s, job_id, status="FAILED", error="domain_inactive")
            return

        await start_job(s, job_id)

        # 기존 페이지 (REMOVED 제외) URL 수집 + root URL 보강
        rows = await s.execute(
            select(Page.url).where(
                Page.domain_id == domain_id,
                Page.status != "REMOVED",
            )
        )
        urls: list[str] = [row[0] for row in rows.all()]
        from kspo_ingest.crawl.start_url import entry_urls
        job = await s.get(CrawlJob, job_id)
        for entry in entry_urls(domain, job):
            if entry not in urls:
                urls.append(entry)
        seed_count = len(urls)

    log.bind(
        event="incremental_start",
        job_id=job_id,
        domain_id=domain_id,
        seed_count=seed_count,
    ).info("incremental started")

    for url in urls:
        async with session_factory() as s:
            if await is_cancelled(s, job_id):
                await finish_job(s, job_id, status="CANCELLED")
                return

        try:
            await _process_one(ctx, job_id=job_id, domain_id=domain_id, url=url)
        except Exception as exc:
            log.bind(
                event="incremental_page_error",
                url=url,
                error=type(exc).__name__,
            ).warning(f"page failed: {exc!s:.200}")

    async with session_factory() as s:
        await bump_stats(s, job_id, discovered=seed_count)
        await finish_crawl_job(s, job_id)
    log.bind(event="incremental_done", job_id=job_id, seed_count=seed_count).info("done")


async def _process_one(ctx: dict, *, job_id: int, domain_id: int, url: str) -> None:
    """단일 URL fetch → clean → (skip 또는 refine → chunk_and_index)."""
    page_id = await fetch_page(ctx, job_id=job_id, domain_id=domain_id, url=url, depth=0)
    if page_id is None:
        return  # dropped/error/removed — fetch_page가 stats 처리 완료

    await extract_links(ctx, job_id=job_id, page_id=page_id)
    cleaned = await clean_page(ctx, job_id=job_id, page_id=page_id)
    if cleaned is None:
        return
    # Apply the age cutoff only to bulletin articles, also during incremental jobs.
    async with ctx["session_factory"]() as session:
        page_row = await session.get(Page, page_id)
        if (
            page_row
            and is_board_article(url, board_source_id=page_row.board_source_id)
            and classify_freshness(page_row.posted_at, freshness_days=settings.board_freshness_days)
            == "stale"
        ):
            await mark_dropped(session, page_id, reason="stale")
            await bump_stats(session, job_id, dropped=1)
            return

    if cleaned.get("skipped"):
        # content_hash 미변경 — refine/chunk 생략
        return

    # Budget guard — 월 예산 100% 초과 시 refine/embed skip
    session_factory = ctx.get("session_factory")
    if session_factory is not None:
        async with session_factory() as s:
            if await is_budget_exceeded(s):
                log.bind(
                    event="budget_exceeded_skip",
                    page_id=page_id,
                ).warning("monthly budget exceeded — skip refine")
                return

    refined = await refine_page(
        ctx,
        job_id=job_id,
        page_id=page_id,
        title=cleaned["title"],
        body_text=cleaned["body_text"],
        content_hash=cleaned["content_hash"],
    )
    if not refined or not refined.get("refined"):
        return

    r = refined["refined"]

    # Quality scoring + embedding policy
    session_factory = ctx.get("session_factory")
    if session_factory is not None:
        async with session_factory() as s:
            domain = await s.get(Domain, domain_id)
            domain_host = domain.host if domain else ""
            page_row = await s.get(Page, page_id)
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
            await upsert_doc_quality(s, page_id=page_id, score=score)

        # Quality gate: quadrant Q4는 저품질 → SONAR 적재 skip. Q1~Q3만 push.
        targets = resolve_embedding_targets(score, url=url)
        if not targets:
            log.bind(
                event="embedding_policy_skip",
                page_id=page_id,
                quadrant=score.quadrant,
                quality=score.quality_score,
            ).info(f"skip sonar push ({score.quadrant})")
            return

        await push_to_sonar(
            ctx,
            job_id=job_id,
            page_id=page_id,
            refined_text=r["refined_text"],
            summary=r.get("summary"),
            keywords=r.get("keywords") or [],
        )
    else:
        # session_factory 없는 경우 (테스트 등) — quality gate 없이 push.
        await push_to_sonar(
            ctx,
            job_id=job_id,
            page_id=page_id,
            refined_text=r["refined_text"],
            summary=r.get("summary"),
            keywords=r.get("keywords") or [],
        )
