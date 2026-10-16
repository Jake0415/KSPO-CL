"""RAG Operations Console — 집계/구조 데이터 소스.

기존 라우터(domains/jobs/pages/kpi/qa/qa_logs)로 커버 안 되는 콘솔 전용 집계만 제공.
모든 수치는 실 DB/Qdrant에서 산출 (mock 없음).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.db.models import BoardSource, Chunk, CrawlJob, Domain, Page
from kspo_ingest.qdrant.client import get_client as get_qdrant
from kspo_ingest.settings import settings

router = APIRouter(prefix="/api/console", tags=["console"])


def _real_schedule(is_active: bool, board_confirmed: int) -> str:
    """실제 운영 스케줄 — worker.py cron_jobs 기준(incremental_cron 필드는 미사용).

    monthly_full_all: 매월 1일 02:00 active 도메인 전체 full.
    daily_board_refresh: 매일 04:00 confirmed board_source 도메인.
    """
    if not is_active:
        return "비활성 — 크롤 안 함"
    parts = ["매월 1일 02:00 전체크롤"]
    if board_confirmed > 0:
        parts.append("매일 04:00 게시판")
    return " · ".join(parts)


class SiteSummary(BaseModel):
    domain_id: int
    host: str
    is_active: bool
    max_depth: int
    max_pages: int
    use_playwright: bool
    indexed: int
    total: int
    last_crawl_at: datetime | None
    schedule: str


@router.get("/sites", response_model=list[SiteSummary])
async def sites_list(s: AsyncSession = SessionDep, _admin: str = AdminDep) -> list[SiteSummary]:
    """사이트별 실 크롤 요약 — 적재수·최근크롤·실제 스케줄(집계 1회)."""
    domains = (await s.execute(select(Domain))).scalars().all()

    indexed_map: dict[int, int] = {}
    total_map: dict[int, int] = {}
    for did, st, cnt in (
        await s.execute(
            select(Page.domain_id, Page.status, func.count()).group_by(Page.domain_id, Page.status)
        )
    ).all():
        total_map[did] = total_map.get(did, 0) + int(cnt)
        if st == "INDEXED":
            indexed_map[did] = indexed_map.get(did, 0) + int(cnt)

    last_map: dict[int, datetime] = {
        did: ts
        for did, ts in (
            await s.execute(
                select(CrawlJob.domain_id, func.max(CrawlJob.finished_at)).group_by(
                    CrawlJob.domain_id
                )
            )
        ).all()
        if ts is not None
    }
    board_map: dict[int, int] = {
        did: int(cnt)
        for did, cnt in (
            await s.execute(
                select(BoardSource.domain_id, func.count())
                .where(BoardSource.status == "confirmed")
                .group_by(BoardSource.domain_id)
            )
        ).all()
    }

    out = [
        SiteSummary(
            domain_id=d.id,
            host=d.host,
            is_active=d.is_active,
            max_depth=d.max_depth,
            max_pages=d.max_pages,
            use_playwright=d.use_playwright,
            indexed=indexed_map.get(d.id, 0),
            total=total_map.get(d.id, 0),
            last_crawl_at=last_map.get(d.id),
            schedule=_real_schedule(d.is_active, board_map.get(d.id, 0)),
        )
        for d in domains
    ]
    out.sort(key=lambda x: x.host)
    return out


class Overview(BaseModel):
    sites_total: int
    sites_active: int
    docs_total: int
    docs_by_status: dict[str, int]
    chunks_total: int
    embeddings_total: int
    failed_crawls: int
    running_crawls: int
    new_docs_today: int
    updated_docs_today: int
    last_crawl_at: datetime | None
    last_embed_at: datetime | None
    crawl_health_pct: float
    system_health: str


async def _qdrant_count() -> int:
    try:
        q = get_qdrant()
        r = await q.count(collection_name=settings.qdrant_index_name, exact=True)
        return int(getattr(r, "count", 0))
    except Exception:
        return 0


@router.get("/overview", response_model=Overview)
async def overview(s: AsyncSession = SessionDep, _admin: str = AdminDep) -> Overview:
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    sites_total = int(await s.scalar(select(func.count()).select_from(Domain)) or 0)
    sites_active = int(
        await s.scalar(select(func.count()).select_from(Domain).where(Domain.is_active)) or 0
    )
    status_rows = (await s.execute(select(Page.status, func.count()).group_by(Page.status))).all()
    docs_by_status = {str(k): int(v) for k, v in status_rows}
    docs_total = sum(docs_by_status.values())
    chunks_total = int(await s.scalar(select(func.count()).select_from(Chunk)) or 0)

    new_docs_today = int(
        await s.scalar(
            select(func.count()).select_from(Page).where(Page.discovered_at >= day_start)
        )
        or 0
    )
    updated_docs_today = int(
        await s.scalar(
            select(func.count()).select_from(Page).where(Page.last_indexed_at >= day_start)
        )
        or 0
    )
    failed_crawls = int(
        await s.scalar(
            select(func.count()).select_from(CrawlJob).where(CrawlJob.status == "FAILED")
        )
        or 0
    )
    running_crawls = int(
        await s.scalar(
            select(func.count()).select_from(CrawlJob).where(CrawlJob.status == "RUNNING")
        )
        or 0
    )
    last_crawl_at = await s.scalar(select(func.max(CrawlJob.finished_at)))
    last_embed_at = await s.scalar(select(func.max(Page.last_indexed_at)))

    # crawl health: 최근 20개 job 중 SUCCESS 비율
    recent = (
        (
            await s.execute(
                select(CrawlJob.status)
                .where(CrawlJob.status.in_(["SUCCESS", "FAILED"]))
                .order_by(CrawlJob.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    ok = sum(1 for st in recent if st == "SUCCESS")
    crawl_health = round(100 * ok / len(recent), 1) if recent else 100.0

    embeddings_total = await _qdrant_count()
    indexed = docs_by_status.get("INDEXED", 0)
    system_health = "healthy" if (indexed > 0 and embeddings_total > 0) else "degraded"

    return Overview(
        sites_total=sites_total,
        sites_active=sites_active,
        docs_total=docs_total,
        docs_by_status=docs_by_status,
        chunks_total=chunks_total,
        embeddings_total=embeddings_total,
        failed_crawls=failed_crawls,
        running_crawls=running_crawls,
        new_docs_today=new_docs_today,
        updated_docs_today=updated_docs_today,
        last_crawl_at=last_crawl_at,
        last_embed_at=last_embed_at,
        crawl_health_pct=crawl_health,
        system_health=system_health,
    )


class ChunkText(BaseModel):
    point_id: str
    text: str
    tags: list[str]


@router.get("/pages/{page_id}/chunks", response_model=list[ChunkText])
async def page_chunks(
    page_id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> list[ChunkText]:
    """페이지의 실제 벡터 청크 본문 — Qdrant payload에서 조회(추출 텍스트 원본)."""
    page = await s.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    try:
        q = get_qdrant()
        res = await q.scroll(
            collection_name=settings.qdrant_index_name,
            scroll_filter={"must": [{"key": "metadata.source", "match": {"value": page.url}}]},
            limit=50,
            with_payload=True,
        )
        points = res[0] if isinstance(res, tuple) else res
        out: list[ChunkText] = []
        for p in points:
            payload = p.payload or {}
            out.append(
                ChunkText(
                    point_id=str(p.id),
                    text=payload.get("page_content", ""),
                    tags=(payload.get("metadata", {}) or {}).get("tags", []),
                )
            )
        return out
    except Exception:
        return []


class UnitCount(BaseModel):
    key: str
    count: int


class SiteStructure(BaseModel):
    domain_id: int
    host: str
    is_active: bool
    max_depth: int
    max_pages: int
    total_pages: int
    by_status: list[UnitCount]
    by_depth: list[UnitCount]
    url_patterns: list[UnitCount]
    attachments: int
    last_crawl_at: datetime | None
    schedule: str
    board_source_count: int


@router.get("/sites/{domain_id}/structure", response_model=SiteStructure)
async def site_structure(
    domain_id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> SiteStructure:
    d = await s.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status_code=404, detail="domain not found")

    by_status = [
        UnitCount(key=str(k), count=int(v))
        for k, v in (
            await s.execute(
                select(Page.status, func.count())
                .where(Page.domain_id == domain_id)
                .group_by(Page.status)
            )
        ).all()
    ]
    by_depth = [
        UnitCount(key=f"depth {k}", count=int(v))
        for k, v in (
            await s.execute(
                select(Page.depth, func.count())
                .where(Page.domain_id == domain_id)
                .group_by(Page.depth)
                .order_by(Page.depth)
            )
        ).all()
    ]
    total_pages = sum(u.count for u in by_status)

    # URL 패턴: path의 2번째 세그먼트(예: /front/board → board) 기준 집계
    seg_expr = func.split_part(func.split_part(Page.url, "://", 2), "/", 3)
    url_patterns = [
        UnitCount(key=(k or "(root)"), count=int(v))
        for k, v in (
            await s.execute(
                select(seg_expr, func.count())
                .where(Page.domain_id == domain_id)
                .group_by(seg_expr)
                .order_by(func.count().desc())
                .limit(20)
            )
        ).all()
    ]
    attachments = int(
        await s.scalar(select(func.count()).select_from(Page).where(Page.domain_id == domain_id))
        or 0
    )
    last_crawl_at = await s.scalar(
        select(func.max(CrawlJob.finished_at)).where(CrawlJob.domain_id == domain_id)
    )
    board_source_count = int(
        await s.scalar(
            select(func.count())
            .select_from(BoardSource)
            .where(BoardSource.domain_id == domain_id, BoardSource.status == "confirmed")
        )
        or 0
    )

    return SiteStructure(
        domain_id=domain_id,
        host=d.host,
        is_active=d.is_active,
        max_depth=d.max_depth,
        max_pages=d.max_pages,
        total_pages=total_pages,
        by_status=by_status,
        by_depth=by_depth,
        url_patterns=url_patterns,
        attachments=attachments,
        last_crawl_at=last_crawl_at,
        schedule=_real_schedule(d.is_active, board_source_count),
        board_source_count=board_source_count,
    )


@router.get("/pages/{page_id}/discovery")
async def page_discovery(
    page_id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> dict:
    """Dynamic coverage evidence; missing report does not imply complete coverage."""
    page = await s.get(Page, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    report = (page.storage_paths or {}).get("discovery_report")
    return {
        "page_id": page.id,
        "source_url": page.url,
        "checked": report is not None,
        "report": report,
    }
