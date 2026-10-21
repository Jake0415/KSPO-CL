"""run_board_refresh — 도메인의 confirmed board_source 목록을 순회하며

3개월 윈도우 내 게시글을 크롤·정제·색인한다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from time import monotonic

from selectolax.parser import HTMLParser
from sqlalchemy import select

from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.crawl.board import (
    build_page_url,
    extract_board_items,
    is_old_board_page,
    is_within_freshness,
    page_param_for_host,
)
from kspo_ingest.crawl.board_identity import is_detail_url
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import BoardSource, Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import (
    finish_crawl_job,
    finish_job,
    is_cancelled,
    job_guard,
    locked_job,
    start_job,
)
from kspo_ingest.tasks.pipeline.board_page import process_board_page
from kspo_ingest.tasks.pipeline.parallel import drain_processing, processing_scope

log = get_logger("worker", "run_board_refresh")

MAX_BOARD_PAGES = 200


async def _record_board_outcome(ctx, job_id, source_id, reason, page_no, list_url):
    partial = reason in {
        "page_limit",
        "time_limit",
        "article_limit",
        "url_limit",
        "no_progress",
        "fetch_error",
        "http_error",
        "parse_error",
        "unparsed_list",
    }
    async with ctx["session_factory"]() as s:
        job = await locked_job(s, job_id)
        if job is not None:
            stats = dict(job.stats or {})
            outcomes = dict(stats.get("board_outcomes") or {})
            outcomes[str(source_id)] = {
                "reason": reason,
                "page": page_no,
                "url": list_url,
                "partial": partial,
            }
            stats.update(
                board_outcomes=outcomes,
                collection_partial=any(v["partial"] for v in outcomes.values()),
            )
            job.stats = stats
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(job, "stats")
            await s.commit()


async def run_board_refresh(
    ctx: dict,
    *,
    job_id: int,
    domain_id: int,
    freshness_days: int | None = None,
    max_pages: int | None = None,
) -> None:
    # Any failure must still leave a terminal job status (no ghost RUNNING).
    # 게시판당 최대 목록 페이지 수(기본 200), 최근 90일 신규 게시글만 처리.
    async with (
        job_guard(ctx["session_factory"], job_id),
        processing_scope(ctx, job_id, domain_id) as run_ctx,
    ):
        await _run_board_refresh_impl(
            run_ctx,
            job_id=job_id,
            domain_id=domain_id,
            freshness_days=freshness_days,
            max_pages=max_pages,
        )


async def _run_board_refresh_impl(
    ctx: dict,
    *,
    job_id: int,
    domain_id: int,
    freshness_days: int | None = None,
    max_pages: int | None = None,
    manage_job: bool = True,
) -> None:
    session_factory = ctx["session_factory"]
    smart_fetcher = ctx["smart_fetcher"]
    rate_limit = ctx["rate_limit"]
    now = datetime.now(UTC)
    eff_freshness = freshness_days or settings.board_freshness_days
    eff_max_pages = min(max_pages or settings.board_max_pages, MAX_BOARD_PAGES)
    if "frontier" in ctx and "full_url_limit" not in ctx:
        ctx = {**ctx, "full_url_limit": 30000}

    async with session_factory() as s:
        domain = await s.get(Domain, domain_id)
        if domain is None:
            await finish_job(s, job_id, status="FAILED", error="domain_not_found")
            return

        ua = domain.user_agent or settings.crawl_user_agent_default
        domain_host = domain.host
        domain_rps = float(domain.rate_limit_rps or 1.5)
        board_page_param = page_param_for_host(
            domain.host
        )  # 사이트별 페이지네이션 파라미터(nPage 등)
        if "full_url_limit" in ctx:
            ctx["full_url_limit"] = min(ctx["full_url_limit"], domain.max_pages or 30000)

        if manage_job:
            await start_job(s, job_id)

        srcs = list(
            (
                await s.execute(
                    select(BoardSource).where(
                        BoardSource.domain_id == domain_id,
                        BoardSource.status.in_(("confirmed", "candidate")),
                    )
                )
            )
            .scalars()
            .all()
        )

    for src in srcs:
        reason = "page_limit"
        started = monotonic()
        deadline = min(
            started + settings.board_max_seconds,
            ctx.setdefault("board_deadline", started + settings.board_total_max_seconds),
        )
        article_count = 0
        seen_articles = set()
        stagnant_pages = 0
        page_no = 1
        list_url = src.list_url
        done = ctx.get("full_board_sources_done")
        if done is not None:
            if src.id in done:
                continue
            done.add(src.id)
        try:
            from kspo_ingest.crawl.board_detect import revalidate_source
            from kspo_ingest.crawl.board_validation import entry_url

            entry = entry_url(src.list_url, domain_host)
            if (
                entry
                and "full_url_limit" in ctx
                and not await ctx["frontier"].admit_direct(
                    job_id, entry, limit=ctx["full_url_limit"]
                )
            ):
                await _record_board_outcome(ctx, job_id, src.id, "url_limit", page_no, list_url)
                continue
            async with session_factory() as s:
                db_src = await s.get(BoardSource, src.id)
                if db_src is None:
                    continue
                async with asyncio.timeout(max(0.001, deadline - monotonic())):
                    verified = await revalidate_source(s, db_src, domain, fetcher=smart_fetcher)
                if not verified:
                    continue
                src.list_url = verified
            page_no = 1
            seen_item_sets = set()
            old_pages = 0
            chronological = bool(src.newest_first)
            previous_date = None
            while page_no <= eff_max_pages:
                if monotonic() >= deadline:
                    reason = "time_limit"
                    break
                async with session_factory() as s:
                    if await is_cancelled(s, job_id):
                        async with session_factory() as s2:
                            await finish_job(s2, job_id, status="CANCELLED")
                        return
                list_url = build_page_url(src.list_url, page_no, param=board_page_param)
                from kspo_ingest.tasks.pipeline.enqueue_seeds import _save_navigation_stats

                await _save_navigation_stats(
                    ctx,
                    job_id,
                    extra={
                        "current_board_url": list_url,
                        "current_board_page": page_no,
                    },
                )
                if "full_url_limit" in ctx and not await ctx["frontier"].admit_direct(
                    job_id, list_url, limit=ctx["full_url_limit"]
                ):
                    reason = "url_limit"
                    break
                try:
                    async with asyncio.timeout(max(0.001, deadline - monotonic())):
                        await rate_limit.acquire(domain_host, domain_rps)
                        result = await smart_fetcher.fetch(list_url, user_agent=ua)
                except TimeoutError:
                    reason = "time_limit"
                    break
                except Exception as exc:
                    reason = "fetch_error"
                    log.bind(event="board_list_fetch_error", url=list_url, err=str(exc)).warning(
                        "fetch failed, skipping source"
                    )
                    break
                if result.http_status >= 400:
                    reason = "http_error"
                    log.bind(
                        event="board_list_http_error",
                        url=list_url,
                        status=result.http_status,
                    ).warning("http error, skipping source")
                    break
                try:
                    enc = detect_encoding(result.raw_bytes, result.content_type)
                    html = result.raw_bytes.decode(enc, errors="replace")
                    items = extract_board_items(html, base_url=list_url)
                except Exception as exc:
                    reason = "parse_error"
                    log.bind(event="board_list_parse_error", url=list_url, err=str(exc)).warning(
                        "parse failed, skipping source"
                    )
                    break
                if not items:
                    links = HTMLParser(html).css("tr a, article a, li a")
                    reason = "unparsed_list" if any(
                        is_detail_url(node.attributes.get("href", ""))
                        or node.attributes.get("onclick")
                        for node in links
                    ) else "empty_list"
                    break
                signature = frozenset(normalize_url(it.url)[1] for it in items)
                if signature in seen_item_sets:
                    reason = "repeated_list"
                    break
                seen_item_sets.add(signature)
                dates = [it.posted_at for it in items if not it.is_notice]
                if dates:
                    if dates != sorted(dates, reverse=True) or (
                        previous_date is not None and dates[0] > previous_date
                    ):
                        chronological = False
                    previous_date = dates[-1]
                ordinary_ids = {normalize_url(it.url)[1] for it in items if not it.is_notice}
                stagnant_pages = stagnant_pages + 1 if not (ordinary_ids - seen_articles) else 0
                seen_articles.update(ordinary_ids)
                if stagnant_pages >= settings.board_no_progress_pages:
                    reason = "no_progress"
                    break
                in_window = [
                    it
                    for it in items
                    if is_within_freshness(it.posted_at, freshness_days=eff_freshness, now=now)
                ]
                # 중복 방지 — 이미 수집(INDEXED/DROPPED)됐거나 content_hash가 있는 글은
                # 재처리하지 않는다. url_hash로 매칭(원본 URL은 pageIndex 등이 달라
                # exact-match 불가). 이 dedup이 없으면 같은 글을 매 페이지 재처리한다.
                if in_window:
                    hash_to_item = {normalize_url(it.url)[1]: it for it in in_window}
                    async with session_factory() as s:
                        rows = await s.execute(
                            select(Page.url_hash).where(
                                Page.domain_id == domain_id,
                                Page.url_hash.in_(list(hash_to_item.keys())),
                                (
                                    (Page.status.in_(("INDEXED", "DROPPED")))
                                    | (Page.content_hash.is_not(None))
                                ),
                                Page.storage_paths["processing_pending"].as_boolean().is_not(True),
                            )
                        )
                        already_done = {r[0] for r in rows.all()}
                    new_items = [it for h, it in hash_to_item.items() if h not in already_done]
                else:
                    new_items = []
                for it in new_items:
                    article_hash = normalize_url(it.url)[1]
                    processed_urls = ctx.setdefault("board_processed_urls", set())
                    if article_hash in processed_urls:
                        continue
                    if article_count >= settings.board_max_articles:
                        reason = "article_limit"
                        break
                    if monotonic() >= deadline:
                        reason = "time_limit"
                        break
                    if "full_url_limit" in ctx and not await ctx["frontier"].admit_direct(
                        job_id, it.url, limit=ctx["full_url_limit"]
                    ):
                        reason = "url_limit"
                        break
                    if "full_board_urls" in ctx:
                        ctx["full_board_urls"].add(normalize_url(it.url)[1])
                    try:
                        processed_urls.add(article_hash)
                        article_count += 1
                        async with asyncio.timeout(max(0.001, deadline - monotonic())):
                            await process_board_page(
                                ctx,
                                job_id=job_id,
                                domain_id=domain_id,
                                board_source_id=src.id,
                                url=it.url,
                                posted_at=it.posted_at,
                            )
                    except TimeoutError:
                        reason = "time_limit"
                        break
                    except Exception as exc:
                        processed_urls.discard(article_hash)
                        log.bind(event="board_page_error", url=it.url, err=str(exc)).warning("skip")
                if reason in {"article_limit", "url_limit", "time_limit"}:
                    break
                # Existing articles never stop pagination. Confirm the date boundary
                # on the next page as well; repeated item sets stop cyclic lists.
                old_pages = (
                    old_pages + 1
                    if is_old_board_page(items, freshness_days=eff_freshness, now=now)
                    else 0
                )
                if chronological and old_pages >= 2:
                    reason = "date_boundary"
                    break
                page_no += 1

            await _record_board_outcome(
                ctx, job_id, src.id, reason, min(page_no, eff_max_pages), list_url
            )
            async with session_factory() as s:
                db_src = await s.get(BoardSource, src.id)
                if db_src:
                    db_src.last_refreshed_at = now
                    await s.commit()
        except Exception as exc:
            await _record_board_outcome(
                ctx,
                job_id,
                src.id,
                "time_limit" if isinstance(exc, TimeoutError) else "fetch_error",
                page_no,
                list_url,
            )
            log.bind(event="board_source_error", source_id=src.id, err=str(exc)).warning(
                "source failed, continuing"
            )

    if manage_job:
        await drain_processing(ctx)
        async with session_factory() as s:
            if not await is_cancelled(s, job_id):
                await finish_crawl_job(s, job_id)
