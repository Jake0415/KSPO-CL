"""Orphan 처리 — 404 카운트 + REMOVED 전환 + 도메인 비활성화 cascade."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import Chunk, Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter

log = get_logger("worker", "orphan")

ORPHAN_404_THRESHOLD = 3


async def handle_404(session: AsyncSession, *, page_id: int, job_id: int | None = None) -> bool:
    """페이지 404 응답 시 호출. error_count++ 후 임계 도달 시 REMOVED 전환.

    Returns:
      True: 페이지가 REMOVED로 전환됨 (호출자가 stats.removed += 1 가능)
      False: 임계 미도달 (그냥 카운트만 증가)
    """
    page = await session.get(Page, page_id)
    if page is None:
        return False

    page.error_count = (page.error_count or 0) + 1
    page.last_http_status = 404
    page.last_fetched_at = datetime.now(UTC)

    if page.error_count < ORPHAN_404_THRESHOLD:
        await session.commit()
        log.bind(
            event="orphan_404_count",
            page_id=page_id,
            error_count=page.error_count,
            threshold=ORPHAN_404_THRESHOLD,
        ).info("404 counted")
        return False

    # 임계 도달 — REMOVED + Qdrant 청크 삭제
    point_ids = await _collect_qdrant_ids(session, page_id=page_id)
    page.status = "REMOVED"
    await session.commit()

    if point_ids:
        try:
            await QdrantDirectAdapter().delete_by_ids(point_ids)
        except Exception as exc:  # noqa: BLE001
            log.bind(
                event="orphan_qdrant_delete_fail",
                page_id=page_id,
                error=type(exc).__name__,
            ).warning(str(exc))

    log.bind(
        event="orphan_removed",
        page_id=page_id,
        deleted_qdrant=len(point_ids),
        job_id=job_id,
    ).info("page REMOVED")
    return True


async def handle_domain_deactivation(session: AsyncSession, *, domain: Domain) -> int:
    """도메인 is_active=false 전환 시 호출. Qdrant + PG 통합 정리.

    1) Qdrant: delete_by_domain — 컬렉션 내 해당 도메인 청크 일괄 삭제
    2) PG: 해당 도메인의 모든 활성 페이지를 REMOVED로 UPDATE
    Returns: Qdrant에서 삭제된 청크 수
    """
    deleted_qdrant = 0
    try:
        deleted_qdrant = await QdrantDirectAdapter().delete_by_domain(domain.host)
    except Exception as exc:  # noqa: BLE001
        log.bind(
            event="orphan_domain_qdrant_fail",
            host=domain.host,
            error=type(exc).__name__,
        ).warning(str(exc))

    await session.execute(
        update(Page)
        .where(Page.domain_id == domain.id, Page.status != "REMOVED")
        .values(status="REMOVED")
    )
    await session.commit()

    log.bind(
        event="orphan_domain_deactivated",
        host=domain.host,
        deleted_qdrant=deleted_qdrant,
    ).info("domain deactivated")
    return deleted_qdrant


async def _collect_qdrant_ids(session: AsyncSession, *, page_id: int) -> list[UUID]:
    rows = await session.execute(
        select(Chunk.qdrant_point_id).where(Chunk.page_id == page_id)
    )
    return [row[0] for row in rows.all()]
