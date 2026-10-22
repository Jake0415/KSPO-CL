"""enqueue_seeds — full Job 진입점. Root URL을 Frontier BFS에 seed하고 순회.

BFS loop: dequeue → fetch → clean → extract_links → refine → score → push_to_sonar.
frontier 비어있거나 max_pages 도달 시 종료.

v2: Quality scoring + publish gate 통합.
    refine 후 score_document → Q1이면 push_to_sonar (SONAR KB 등록·색인).
    Q2~Q4는 doc_quality에 기록만 하고 SONAR push 스킵.
"""

from __future__ import annotations

from sqlalchemy import delete, select

from kspo_ingest.crawl.board import classify_freshness
from kspo_ingest.crawl.board_identity import is_board_owned_link
from kspo_ingest.crawl.frontier import Frontier
from kspo_ingest.crawl.sitemap import discover_sitemap_urls, parse_sitemap
from kspo_ingest.crawl.soma import is_board_article
from kspo_ingest.db.models import BoardSource, CrawlJob, Domain, Page
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
    locked_job,
    start_job,
)
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.extract_links import extract_links
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.helpers import mark_dropped
from kspo_ingest.tasks.pipeline.parallel import (
    PublicationError,
    drain_processing,
    processing_scope,
    submit_postprocessing,
)
from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar
from kspo_ingest.tasks.pipeline.refine_page import refine_page

log = get_logger("worker", "enqueue_seeds")


async def enqueue_seeds(ctx: dict, *, job_id: int, domain_id: int) -> None:
    # Any failure in the BFS body must still leave a terminal job status.
    async with (
        job_guard(ctx["session_factory"], job_id),
        processing_scope(ctx, job_id, domain_id) as run_ctx,
    ):
        await _enqueue_seeds_impl(run_ctx, job_id=job_id, domain_id=domain_id)


async def _enqueue_seeds_impl(ctx: dict, *, job_id: int, domain_id: int) -> None:
    session_factory = ctx["session_factory"]
    frontier: Frontier = ctx["frontier"]

    async with session_factory() as s:
        domain = await s.get(Domain, domain_id)
        if domain is None:
            await finish_job(s, job_id, status="FAILED", error="domain_not_found")
            return

        existing_job = await s.get(CrawlJob, job_id)
        if getattr(existing_job, "status", None) == "CANCELLED":
            return
        await start_job(s, job_id)
        from kspo_ingest.crawl.start_url import entry_urls, preflight_start

        job = await s.get(CrawlJob, job_id)
        seeds = entry_urls(domain, job)
        max_pages = min(domain.max_pages or 30000, 30000)
        max_depth = domain.max_depth if domain.max_depth is not None else 10

    # Validate entry points before removing any existing data or index.
    await preflight_start(ctx, domain, seeds)
    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return

    # Full means replacement, not a DISCOVERED-only incremental pass.
    # SONAR deletion also removes its RAG index; fail before PG reset if it fails.
    async with session_factory() as s:
        rows = await s.execute(select(Page.id).where(Page.domain_id == domain_id))
        old_page_ids = [row[0] for row in rows.all()]
    sonar = ctx.get("sonar_client")
    if sonar is not None:
        await sonar.reset_site(host=domain.host, namespace=ctx["sonar_namespace"])
    elif ctx.get("local_direct_indexing"):
        from kspo_ingest.qdrant.adapter import QdrantDirectAdapter

        adapter = QdrantDirectAdapter()
        for collection in (
            settings.qdrant_index_name,
            settings.qdrant_knowledge_collection,
            settings.qdrant_archive_collection,
        ):
            adapter.collection = collection
            await adapter.delete_by_domain(domain.host)
    elif old_page_ids:
        raise RuntimeError("Full reset requires SONAR client to remove existing RAG data")
    async with session_factory() as s:
        await s.execute(delete(Page).where(Page.domain_id == domain_id))
        # Full replacement also resets candidate/confirmed/rejected/invalid source records.
        # Keep the deletion scoped to this site; rediscovery rebuilds verified first-entry URLs.
        await s.execute(delete(BoardSource).where(BoardSource.domain_id == domain_id))
        await s.commit()  # Page cascades remove chunks, attachments and document quality.
    import asyncio

    await asyncio.to_thread(_remove_site_storage, ctx["storage_root"], domain_id, old_page_ids)
    # Clear any frontier left by an interrupted attempt of this same job.
    await frontier.redis.delete(
        frontier._k_frontier(job_id),
        frontier._k_seen(job_id),
        frontier._k_inflight(job_id),
        f"duplicates:{job_id}",
        f"url_limit:{job_id}",
        f"list_states:{job_id}",
        f"blocked_lists:{job_id}",
        f"content_states:{job_id}",
        f"admitted:{job_id}",
        f"repeated_lists:{job_id}",
    )

    await frontier.redis.set(f"crawl_limit:{job_id}", max_pages)
    for seed_url in seeds:
        await frontier.enqueue(job_id, seed_url, depth=0)
    ctx = {
        **ctx,
        "new_discoveries": [],
        "full_board_sources_done": set(),
        "full_board_urls": set(),
        "full_url_limit": max_pages,
    }
    from kspo_ingest.tasks.pipeline.run_board_refresh import _run_board_refresh_impl

    # Seed sitemap URLs (best-effort — 실패해도 BFS는 계속)
    try:
        sm_urls = await discover_sitemap_urls(domain.host)
        for sm_url in sm_urls:
            entries = await parse_sitemap(sm_url)
            for entry in entries:
                await frontier.enqueue(job_id, entry.url, depth=1)
        if sm_urls:
            log.bind(
                event="sitemap_seeds",
                job_id=job_id,
                sitemaps=len(sm_urls),
            ).info("sitemap URLs seeded")
    except Exception:
        log.bind(event="sitemap_seed_skip", job_id=job_id).debug("sitemap discovery skipped")

    processed = 0
    while processed < max_pages:
        # Flush before checking for exhaustion, including discoveries retained
        # after a transient queue failure on the preceding page.
        await _enqueue_discovered(ctx, job_id=job_id, domain_id=domain_id)
        await _save_navigation_stats(ctx, job_id)
        item = await frontier.dequeue(job_id)
        if item is None:
            break  # Frontier empty — BFS complete

        url, depth = item
        from kspo_ingest.crawl.url_normalize import normalize_url

        if normalize_url(url)[1] in ctx["full_board_urls"]:
            await frontier.ack(job_id, url)
            continue
        from kspo_ingest.crawl.loop_guard import list_family

        family = list_family(url)
        async with session_factory() as s:
            owned = set(
                (
                    await s.execute(
                        select(BoardSource.list_url).where(
                            BoardSource.domain_id == domain_id, BoardSource.status == "confirmed"
                        )
                    )
                )
                .scalars()
                .all()
            )
        if is_board_owned_link(url, confirmed_list_urls=owned):
            await frontier.ack(job_id, url)
            continue
        if family and await frontier.redis.sismember(f"blocked_lists:{job_id}", family):
            await frontier.ack(job_id, url)
            await frontier.redis.incr(f"repeated_lists:{job_id}")
            continue

        async with session_factory() as s:
            if await is_cancelled(s, job_id):
                await frontier.ack(job_id, url)
                await finish_job(s, job_id, status="CANCELLED")
                return

        if depth > max_depth:
            await frontier.ack(job_id, url)
            continue

        # Per-page 격리: 한 페이지의 예외(인코딩 오류 등)가 전체 BFS를 죽이지
        # 않도록 격리한다. 실패 페이지는 로깅 후 ack+skip하고 크롤을 계속한다.
        try:
            page_id = await fetch_page(
                ctx, job_id=job_id, domain_id=domain_id, url=url, depth=depth
            )
            if page_id is None:
                await frontier.ack(job_id, url)
                processed += 1
                continue

            await extract_links(ctx, job_id=job_id, page_id=page_id)
            await _run_board_refresh_impl(ctx, job_id=job_id, domain_id=domain_id, manage_job=False)
            await _enqueue_discovered(ctx, job_id=job_id, domain_id=domain_id)

            cleaned = await clean_page(ctx, job_id=job_id, page_id=page_id)
            if cleaned is None:
                await frontier.ack(job_id, url)
                processed += 1
                continue

            import hashlib

            body_hash = hashlib.sha256(cleaned.get("body_text", "").encode()).hexdigest()
            if cleaned.get("body_text"):
                await frontier.redis.sadd(f"content_states:{job_id}", body_hash)

            # Bulletin articles only: skip content older than the configured 90-day window.
            # 무날짜 글은 유지(수집)하고 링크 발견(extract_links) 이후에 판정하므로
            # 하위 탐색도 유지된다.
            async with session_factory() as s:
                _pr = await s.get(Page, page_id)
                _posted = getattr(_pr, "posted_at", None) if _pr else None
            if (
                is_board_article(url, board_source_id=getattr(_pr, "board_source_id", None))
                and classify_freshness(_posted, freshness_days=settings.board_freshness_days)
                == "stale"
            ):
                async with session_factory() as s:
                    await mark_dropped(s, page_id, reason="stale")
                    await bump_stats(s, job_id, dropped=1)
                await frontier.ack(job_id, url)
                processed += 1
                continue

            # content_hash 미변경 → clean_page가 {"skipped": True}(title 없음) 반환.
            # 재크롤 시 refine/embed 생략. 이 가드가 없으면 아래 cleaned["title"]에서
            # KeyError로 full 크롤이 크래시한다 (재크롤 불가 버그).
            if cleaned.get("skipped"):
                await frontier.ack(job_id, url)
                processed += 1
                continue

            await submit_postprocessing(
                ctx,
                job_id,
                page_id,
                lambda pid=page_id, u=url, body=cleaned: _finish_page(
                    ctx, job_id=job_id, domain_id=domain_id, page_id=pid, url=u, cleaned=body
                ),
            )
        except Exception as exc:
            async with session_factory() as error_session:
                await bump_stats(error_session, job_id, errors=1)
            log.bind(event="page_process_error", url=url, err=str(exc)).warning(
                "페이지 처리 실패 — 건너뛰고 계속"
            )

        await frontier.ack(job_id, url)
        processed += 1

    await drain_processing(ctx)
    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return
    await _save_navigation_stats(ctx, job_id)
    async with session_factory() as s:
        job = await s.get(CrawlJob, job_id)
        from sqlalchemy.orm.attributes import flag_modified

        if job:
            job.stats = dict(job.stats or {})
            job.stats["termination_reason"] = (
                "url_limit"
                if processed >= max_pages or await frontier.redis.get(f"url_limit:{job_id}")
                else "queue_exhausted"
            )
            if job.stats["termination_reason"] == "url_limit":
                job.stats["collection_partial"] = True
            flag_modified(job, "stats")
            await s.commit()
        await finish_crawl_job(s, job_id)

    log.bind(
        event="enqueue_seeds_done",
        job_id=job_id,
        domain_id=domain_id,
        processed=processed,
    ).info("BFS done")


async def _finish_page(
    ctx: dict, *, job_id: int, domain_id: int, page_id: int, url: str, cleaned: dict
):
    session_factory = ctx["session_factory"]
    # Budget guard — 월 예산 100% 초과 시 refine/embed skip
    async with session_factory() as s:
        if await is_budget_exceeded(s):
            log.bind(
                event="budget_exceeded_skip",
                page_id=page_id,
            ).warning("monthly budget exceeded — skip refine")
            return False

    refined = await refine_page(
        ctx,
        job_id=job_id,
        page_id=page_id,
        title=cleaned["title"],
        body_text=cleaned["body_text"],
        content_hash=cleaned["content_hash"],
    )

    if refined and refined.get("refined"):
        r = refined["refined"]

        # Quality scoring + quadrant 배정
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
                is_meaningful=True,  # refine 통과했으므로
                domain_host=domain_host,
            )
        )

        async with session_factory() as s:
            await upsert_doc_quality(s, page_id=page_id, score=score)

        # Embedding policy: quadrant별 대상 컬렉션 결정
        targets = resolve_embedding_targets(score, url=url)
        if targets:
            sent = await push_to_sonar(
                ctx,
                job_id=job_id,
                page_id=page_id,
                refined_text=r["refined_text"],
                summary=r.get("summary"),
                keywords=r.get("keywords") or [],
            )
            if sent == 0:
                raise PublicationError(
                    "Sonar publication failed", counted=bool(ctx.get("sonar_client"))
                )
        else:
            log.bind(
                event="embedding_policy_skip",
                page_id=page_id,
                quadrant=score.quadrant,
                quality=score.quality_score,
            ).info(f"skip embed ({score.quadrant})")


async def _enqueue_discovered(ctx: dict, *, job_id: int, domain_id: int) -> int:
    """Drain committed discoveries from this job, without rescanning pages.

    Remove a buffered item only after Redis accepted it (or explicitly rejected
    it as duplicate/over budget). On an exception retain the unprocessed suffix;
    the next loop must drain it before declaring the frontier exhausted.
    """
    pending = ctx["new_discoveries"]
    if not pending:
        return 0
    from kspo_ingest.crawl.url_class import is_search_result_url

    async with ctx["session_factory"]() as s:
        confirmed = set(
            (
                await s.execute(
                    select(BoardSource.list_url).where(
                        BoardSource.domain_id == domain_id, BoardSource.status == "confirmed"
                    )
                )
            )
            .scalars()
            .all()
        )
    completed = enqueued = 0
    try:
        for url, depth in pending:
            if not is_search_result_url(url) and not is_board_owned_link(
                url, confirmed_list_urls=confirmed
            ):
                enqueued += bool(await ctx["frontier"].enqueue(job_id, url, depth))
            completed += 1
    finally:
        del pending[:completed]
    return enqueued


def _remove_site_storage(storage_path, domain_id: int, old_page_ids: list[int]) -> None:
    import shutil
    from pathlib import Path

    storage_root = Path(storage_path).resolve()
    cleanup_paths = [
        storage_root / "raw" / str(domain_id),
        storage_root / "attachments" / str(domain_id),
    ]
    cleanup_paths.extend(storage_root / "refined" / str(ident) for ident in old_page_ids)
    for candidate in cleanup_paths:
        target = candidate.resolve()
        if not target.is_relative_to(storage_root) or target == storage_root:
            raise RuntimeError("Unsafe full reset storage path")
        if target.exists():
            shutil.rmtree(target)


async def _save_navigation_stats(ctx: dict, job_id: int, *, extra: dict | None = None) -> None:
    from sqlalchemy.orm.attributes import flag_modified

    if "frontier" not in ctx:
        return
    frontier = ctx["frontier"]
    redis = frontier.redis
    values = {
        "discovered": int(await redis.scard(frontier._k_seen(job_id))),
        "pending_urls": await frontier.size(job_id),
        "duplicate_urls": int(await redis.get(f"duplicates:{job_id}") or 0),
        "unique_contents": int(await redis.scard(f"content_states:{job_id}")),
        "repeated_lists": int(await redis.get(f"repeated_lists:{job_id}") or 0),
    }
    async with ctx["session_factory"]() as s:
        job = await locked_job(s, job_id)
        if job:
            job.stats = {**(job.stats or {}), **values, **(extra or {})}
            flag_modified(job, "stats")
            await s.commit()
