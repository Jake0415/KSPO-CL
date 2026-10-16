"""run_board_refresh — 도메인의 confirmed board_source 목록을 순회하며

3개월 윈도우 내 게시글을 크롤·정제·색인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.crawl.board import (
    build_page_url,
    extract_board_items,
    is_within_freshness,
    page_param_for_host,
)
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import BoardSource, Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import finish_job, is_cancelled, job_guard, start_job
from kspo_ingest.tasks.pipeline.board_page import process_board_page

log = get_logger("worker", "run_board_refresh")

MAX_BOARD_PAGES = 200


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
    async with job_guard(ctx["session_factory"], job_id):
        await _run_board_refresh_impl(
            ctx,
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
    eff_max_pages = max_pages or MAX_BOARD_PAGES

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
                continue
            async with session_factory() as s:
                db_src = await s.get(BoardSource, src.id)
                if db_src is None:
                    continue
                verified = await revalidate_source(s, db_src, domain, fetcher=smart_fetcher)
                if not verified:
                    continue
                src.list_url = verified
            page_no = 1
            seen_item_sets = set()
            old_pages = 0
            while page_no <= eff_max_pages:
                async with session_factory() as s:
                    if await is_cancelled(s, job_id):
                        async with session_factory() as s2:
                            await finish_job(s2, job_id, status="CANCELLED")
                        return
                list_url = build_page_url(src.list_url, page_no, param=board_page_param)
                if "full_url_limit" in ctx and not await ctx["frontier"].admit_direct(
                    job_id, list_url, limit=ctx["full_url_limit"]
                ):
                    break
                try:
                    await rate_limit.acquire(domain_host, domain_rps)
                    result = await smart_fetcher.fetch(list_url, user_agent=ua)
                except Exception as exc:
                    log.bind(event="board_list_fetch_error", url=list_url, err=str(exc)).warning(
                        "fetch failed, skipping source"
                    )
                    break
                if result.http_status >= 400:
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
                    log.bind(event="board_list_parse_error", url=list_url, err=str(exc)).warning(
                        "parse failed, skipping source"
                    )
                    break
                if not items:
                    break
                signature = frozenset(normalize_url(it.url)[1] for it in items)
                if signature in seen_item_sets:
                    break
                seen_item_sets.add(signature)
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
                                (Page.status.in_(("INDEXED", "DROPPED")))
                                | (Page.content_hash.is_not(None)),
                            )
                        )
                        already_done = {r[0] for r in rows.all()}
                    new_items = [it for h, it in hash_to_item.items() if h not in already_done]
                else:
                    new_items = []
                for it in new_items:
                    if "full_url_limit" in ctx and not await ctx["frontier"].admit_direct(
                        job_id, it.url, limit=ctx["full_url_limit"]
                    ):
                        break
                    if "full_board_urls" in ctx:
                        ctx["full_board_urls"].add(normalize_url(it.url)[1])
                    try:
                        await process_board_page(
                            ctx,
                            job_id=job_id,
                            domain_id=domain_id,
                            board_source_id=src.id,
                            url=it.url,
                            posted_at=it.posted_at,
                        )
                    except Exception as exc:
                        log.bind(event="board_page_error", url=it.url, err=str(exc)).warning("skip")
                # Existing articles never stop pagination. Confirm the date boundary
                # on the next page as well; repeated item sets stop cyclic lists.
                old_pages = old_pages + 1 if not in_window else 0
                if src.newest_first and old_pages >= 2:
                    break
                page_no += 1

            async with session_factory() as s:
                db_src = await s.get(BoardSource, src.id)
                if db_src:
                    db_src.last_refreshed_at = now
                    await s.commit()
        except Exception as exc:
            log.bind(event="board_source_error", source_id=src.id, err=str(exc)).warning(
                "source failed, continuing"
            )

    if manage_job:
        async with session_factory() as s:
            await finish_job(s, job_id, status="SUCCESS")
