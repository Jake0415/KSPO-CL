"""ARQ cron 정의 — monthly_full_all + refresh_stats_views 외.

ARQ 0.28의 cron()에는 timezone 인자가 없으므로 컨테이너 TZ에 의존한다.
docker-compose.yml에서 worker 서비스는 `TZ=Asia/Seoul`로 시작되므로 hour={2}는
02:00 KST를 의미한다. UTC 환경에서 돌리면 17:00 UTC(전일).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import and_, func, or_, select, text

from kspo_ingest.crawl.board_frequency import classify_board_tier
from kspo_ingest.db.models import BoardSource, CrawlJob, DocQuality, Domain, Page
from kspo_ingest.db.models import Chunk as ChunkRow
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
from kspo_ingest.quality.gate import mark_archived
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import empty_stats

log = get_logger("cron", "scheduler")


_arq_pool = None


async def _get_pool():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq_pool


async def monthly_full_all(ctx: dict) -> dict:
    """매월 1일 02:00 KST — active 도메인 전체 full 크롤(enqueue_seeds)."""
    session_factory = ctx["session_factory"]
    pool = await _get_pool()
    enqueued = 0
    async with session_factory() as s:
        rows = await s.execute(select(Domain).where(Domain.is_active.is_(True)))
        domains = list(rows.scalars().all())
        for d in domains:
            active = await s.scalar(
                select(func.count())
                .select_from(CrawlJob)
                .where(
                    CrawlJob.domain_id == d.id,
                    CrawlJob.status.in_(["PENDING", "RUNNING"]),
                )
            )
            if active and active > 0:
                continue
            job = CrawlJob(
                domain_id=d.id,
                job_type="full",
                status="PENDING",
                triggered_by="cron_monthly",
                stats=empty_stats(),
            )
            s.add(job)
            await s.commit()
            await s.refresh(job)
            arq_job = await pool.enqueue_job("enqueue_seeds", job_id=job.id, domain_id=d.id)
            job.arq_job_id = arq_job.job_id if arq_job else None
            await s.commit()
            enqueued += 1
    log.bind(event="monthly_full_all", enqueued=enqueued).info("monthly full cron tick")
    return {"enqueued": enqueued}


async def daily_board_refresh(ctx: dict) -> dict:
    """매일 04:00 KST — confirmed board_source가 있는 active 도메인의 board Job enqueue."""
    session_factory = ctx["session_factory"]
    pool = await _get_pool()
    enqueued = 0
    async with session_factory() as s:
        rows = await s.execute(
            select(Domain.id)
            .join(BoardSource, BoardSource.domain_id == Domain.id)
            .where(Domain.is_active.is_(True), BoardSource.status.in_(("confirmed", "candidate")))
            .distinct()
        )
        domain_ids = [r[0] for r in rows.all()]
        for did in domain_ids:
            active = await s.scalar(
                select(func.count())
                .select_from(CrawlJob)
                .where(
                    CrawlJob.domain_id == did,
                    CrawlJob.status.in_(["PENDING", "RUNNING"]),
                )
            )
            if active and active > 0:
                continue
            job = CrawlJob(
                domain_id=did,
                job_type="board",
                status="PENDING",
                triggered_by="cron_board",
                stats=empty_stats(),
            )
            s.add(job)
            await s.commit()
            await s.refresh(job)
            arq_job = await pool.enqueue_job("run_board_refresh", job_id=job.id, domain_id=did)
            job.arq_job_id = arq_job.job_id if arq_job else None
            await s.commit()
            enqueued += 1
    log.bind(event="daily_board_refresh", enqueued=enqueued).info("daily board cron tick")
    return {"enqueued": enqueued}


async def refresh_stats_views(ctx: dict) -> dict:
    """5분 주기 — v_stats_overview 갱신.

    REFRESH CONCURRENTLY 시도 → 첫 호출 등 실패 시 일반 REFRESH로 fallback.
    v_cost_daily는 일반 view라 갱신 불필요.
    """
    session_factory = ctx["session_factory"]
    mode = "concurrently"
    async with session_factory() as s:
        try:
            await s.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY v_stats_overview;"))
            await s.commit()
        except Exception as exc:  # noqa: BLE001
            mode = "fallback"
            log.bind(
                event="stats_refresh_fallback",
                error=type(exc).__name__,
            ).warning(str(exc))
            await s.rollback()
            await s.execute(text("REFRESH MATERIALIZED VIEW v_stats_overview;"))
            await s.commit()
    log.bind(event="stats_refresh_ok", mode=mode).info("v_stats_overview refreshed")
    return {"mode": mode}


async def archive_expired_documents(ctx: dict) -> dict:
    """매일 05:00 KST — freshness_score < 0.2인 Q1/Q2/Q3 문서를 Q4(archive)로 전환.

    tilellm/kspo_knowledge에서 해당 포인트 삭제 + DB archived_at 갱신.
    """
    session_factory = ctx["session_factory"]
    threshold = 0.2
    archived = 0
    cutoff = datetime.now(UTC) - timedelta(days=settings.board_freshness_days)

    async with session_factory() as s:
        rows = await s.execute(
            select(DocQuality)
            .join(Page, Page.id == DocQuality.page_id)
            .where(
                DocQuality.archived_at.is_(None),
                # 게시글 제외 — archive_expired_board_posts에서 처리
                Page.board_source_id.is_(None),
                or_(
                    and_(
                        DocQuality.freshness_score < threshold,
                        DocQuality.quadrant.in_(["Q1", "Q2", "Q3"]),
                    ),
                    Page.posted_at < cutoff,
                ),
            )
        )
        docs = list(rows.scalars().all())

        if not docs:
            return {"archived": 0}

        adapter = QdrantDirectAdapter()
        active_collections = [
            settings.qdrant_index_name,
            settings.qdrant_knowledge_collection,
        ]

        for dq in docs:
            # Qdrant에서 해당 페이지 청크 삭제
            chunk_rows = await s.execute(
                select(ChunkRow.qdrant_point_id).where(
                    ChunkRow.page_id == dq.page_id,
                )
            )
            point_ids = [r[0] for r in chunk_rows.all() if r[0]]

            if point_ids:
                for col in active_collections:
                    try:
                        await adapter.delete_from_collection(
                            col,
                            point_ids,
                        )
                    except Exception:
                        log.bind(
                            event="archive_delete_skip",
                            collection=col,
                            page_id=dq.page_id,
                        ).debug("collection delete skipped")

            await mark_archived(s, dq.page_id)
            archived += 1

    log.bind(
        event="archive_expired",
        archived=archived,
    ).info("archive cron tick")
    return {"archived": archived}


async def archive_expired_board_posts(ctx: dict) -> dict:
    """매일 05:30 KST — posted_at이 board_freshness_days 경과한 게시글을 kspo_archive로 이동.

    tilellm/kspo_knowledge에서 해당 포인트를 move_points로 kspo_archive로 이전.
    """
    session_factory = ctx["session_factory"]
    cutoff = datetime.now(UTC) - timedelta(days=settings.board_freshness_days)
    adapter = QdrantDirectAdapter()
    active_cols = [settings.qdrant_index_name, settings.qdrant_knowledge_collection]
    archive_col = settings.qdrant_archive_collection
    archived = 0

    async with session_factory() as s:
        rows = await s.execute(
            select(Page).where(
                Page.board_source_id.is_not(None),
                Page.posted_at < cutoff,
                Page.status == "INDEXED",
            )
        )
        pages = list(rows.scalars().all())

        for page in pages:
            chunk_rows = await s.execute(
                select(ChunkRow.qdrant_point_id).where(ChunkRow.page_id == page.id)
            )
            point_ids = [r[0] for r in chunk_rows.all() if r[0]]

            if point_ids:
                for col in active_cols:
                    try:
                        await adapter.move_points(col, archive_col, point_ids)
                    except Exception:
                        log.bind(
                            event="board_archive_move_skip",
                            collection=col,
                            page_id=page.id,
                        ).debug("skip")

            page.status = "ARCHIVED"
            await mark_archived(s, page.id)
            archived += 1

    log.bind(event="archive_expired_board_posts", archived=archived).info("board archive tick")
    return {"archived": archived}


def _daily_board_urls_for_domain(groups: list[tuple[str, int, int, str]]) -> list[str]:
    """(path, d30, d90, list_url) 목록 → DAILY 티어의 list_url만."""
    return [lu for (_p, d30, d90, lu) in groups if classify_board_tier(d30, d90) == "DAILY"]


async def auto_register_daily_boards(ctx: dict) -> dict:
    """주 1회 — 빈도 실측으로 DAILY 게시판을 confirmed board_source로 upsert."""
    session_factory = ctx["session_factory"]
    registered = 0
    async with session_factory() as s:
        rows = await s.execute(
            text(
                """
                -- 게시판 정체성은 '목록 URL'이다. 목록 페이지가 크롤되길 기다리지 않고
                -- 수집된 게시글(view.do)에서 목록 URL을 역산한다 — crawl/board.py의
                -- canonical_board_list_url()과 동일 규칙(view/list.do→list.do, menuNo만 유지).
                -- 그 결과 같은 게시판의 모든 변형이 하나의 키로 수렴하고, 게시글이 있는
                -- 모든 게시판이 빈도 기반으로 자동 포착된다.
                WITH derived AS (
                  SELECT p.domain_id,
                         regexp_replace(split_part(p.url,'?',1), '/(view|list)\\.do$', '/list.do')
                           || '?menuNo=' || substring(p.url from 'menuNo=([0-9]+)') AS list_url,
                         p.posted_at
                  FROM pages p JOIN domains d ON d.id=p.domain_id
                  WHERE d.is_active AND d.host<>'www.naver.com'
                    AND p.posted_at IS NOT NULL
                    AND (split_part(p.url,'?',1) LIKE '%/view.do'
                         OR split_part(p.url,'?',1) LIKE '%/list.do')
                    AND p.url ~ 'menuNo=[0-9]+'
                )
                SELECT domain_id,
                       count(*) FILTER (WHERE posted_at>now()-interval '30 days') d30,
                       count(*) FILTER (WHERE posted_at>now()-interval '90 days') d90,
                       list_url
                FROM derived
                GROUP BY domain_id, list_url
                HAVING count(*)>=3
                """
            )
        )
        for domain_id, d30, d90, list_url in rows.all():
            if classify_board_tier(int(d30), int(d90)) != "DAILY":
                continue
            from kspo_ingest.crawl.board_detect import upsert_board_candidate

            try:
                src = await upsert_board_candidate(
                    s, domain_id=domain_id, list_url=list_url, fetcher=ctx.get("smart_fetcher")
                )
                if src is not None and src.status == "confirmed":
                    registered += 1
            except Exception as exc:
                log.bind(
                    event="board_validation_failed", domain_id=domain_id, err=type(exc).__name__
                ).warning("board registration skipped")
        await s.commit()
    log.bind(event="auto_register_daily_boards", registered=registered).info("auto register tick")
    return {"registered": registered}
