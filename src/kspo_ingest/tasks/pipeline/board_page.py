"""board_page — 게시판 상세 1건 처리: page 선생성 → 기존 per-page 체인 재사용."""

from __future__ import annotations

from datetime import datetime

from kspo_ingest.crawl.board import classify_freshness
from kspo_ingest.crawl.soma import is_board_article
from kspo_ingest.db.models import Domain, Page
from kspo_ingest.observability.cost_monitor import is_budget_exceeded
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.quality.gate import upsert_doc_quality
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import bump_stats
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.extract_links import extract_links
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page, mark_dropped
from kspo_ingest.tasks.pipeline.parallel import PublicationError, submit_postprocessing
from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar
from kspo_ingest.tasks.pipeline.refine_page import refine_page

log = get_logger("worker", "board_page")


async def process_board_page(
    ctx: dict,
    *,
    job_id: int,
    domain_id: int,
    board_source_id: int,
    url: str,
    posted_at: datetime,
) -> None:
    """게시판 상세 1건: page 선생성(board_source_id+posted_at) → 기존 per-page 체인."""
    session_factory = ctx["session_factory"]

    async with session_factory() as s:
        await get_or_create_page(
            s,
            domain_id=domain_id,
            url=url,
            depth=0,
            board_source_id=board_source_id,
            posted_at=posted_at,
        )

    page_id = await fetch_page(ctx, job_id=job_id, domain_id=domain_id, url=url, depth=0)
    if page_id is None:
        return

    await extract_links(ctx, job_id=job_id, page_id=page_id)
    cleaned = await clean_page(ctx, job_id=job_id, page_id=page_id)
    if cleaned is None:
        return
    if "full_url_limit" in ctx and cleaned.get("body_text"):
        import hashlib

        await ctx["frontier"].redis.sadd(
            f"content_states:{job_id}",
            hashlib.sha256(cleaned["body_text"].encode()).hexdigest(),
        )

    async with session_factory() as s:
        page = await s.get(Page, page_id)
        if (
            page
            and is_board_article(url, board_source_id=page.board_source_id)
            and (
                classify_freshness(page.posted_at, freshness_days=settings.board_freshness_days)
                == "stale"
            )
        ):
            await mark_dropped(s, page_id, reason="stale")
            await bump_stats(s, job_id, dropped=1)
            return
        if cleaned.get("skipped"):
            return
        if await is_budget_exceeded(s):
            log.bind(event="budget_exceeded_skip", page_id=page_id).warning(
                "monthly budget exceeded — skip refine"
            )
            return

    await submit_postprocessing(
        ctx,
        job_id,
        page_id,
        lambda: _finish_page(
            ctx, job_id=job_id, domain_id=domain_id, page_id=page_id, url=url, cleaned=cleaned
        ),
    )


async def _finish_page(
    ctx: dict, *, job_id: int, domain_id: int, page_id: int, url: str, cleaned: dict
):
    session_factory = ctx["session_factory"]
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

    targets = resolve_embedding_targets(score, url=url)
    if not targets:
        return

    sent = await push_to_sonar(
        ctx,
        job_id=job_id,
        page_id=page_id,
        refined_text=r["refined_text"],
        summary=r.get("summary"),
        keywords=r.get("keywords") or [],
    )
    if sent == 0:
        raise PublicationError("Sonar publication failed", counted=bool(ctx.get("sonar_client")))
