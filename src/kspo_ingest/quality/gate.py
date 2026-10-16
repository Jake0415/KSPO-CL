"""Publish gate — doc_quality 기반으로 tilellm publish 여부 결정.

refine_page → score_document → upsert_doc_quality → should_publish → chunk_and_index
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import DocQuality
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.quality.scorer import SCORER_VERSION, ScoreResult

log = get_logger("quality", "gate")


async def upsert_doc_quality(
    session: AsyncSession,
    *,
    page_id: int,
    score: ScoreResult,
) -> None:
    """doc_quality INSERT … ON CONFLICT UPDATE."""
    values = {
        "page_id": page_id,
        "quality_score": Decimal(str(score.quality_score)),
        "structure_score": Decimal(str(score.structure_score)),
        "freshness_score": Decimal(str(score.freshness_score)),
        "trust_score": Decimal(str(score.trust_score)),
        "importance_score": Decimal("0"),
        "duplicate_score": Decimal(str(score.duplicate_score)),
        "quadrant": score.quadrant,
        "extraction_method": score.extraction_method,
        "body_length": score.body_length,
        "korean_ratio": Decimal(str(score.korean_ratio)),
        "has_title": score.has_title,
        "has_posted_at": score.has_posted_at,
        "has_summary": score.has_summary,
        "keyword_count": score.keyword_count,
        "scorer_version": SCORER_VERSION,
        "scored_at": datetime.now(UTC),
    }

    stmt = pg_insert(DocQuality).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["page_id"],
        set_={k: v for k, v in values.items() if k != "page_id"},
    )
    await session.execute(stmt)
    await session.commit()

    log.bind(
        event="doc_quality_upserted",
        page_id=page_id,
        quadrant=score.quadrant,
        quality=score.quality_score,
        structure=score.structure_score,
    ).info("quality scored")


def should_publish(score: ScoreResult) -> bool:
    """tilellm에 publish할지 결정.

    조건:
    - quadrant == Q1
    - quality_score >= 0.6
    - freshness_score >= 0.3
    - duplicate_score >= 0.5
    """
    return (
        score.quadrant == "Q1"
        and score.quality_score >= 0.6
        and score.freshness_score >= 0.3
        and score.duplicate_score >= 0.5
    )


async def mark_published(session: AsyncSession, page_id: int) -> None:
    """publish 완료 시 published_at 갱신."""
    dq = await session.get(DocQuality, page_id)
    if dq is not None:
        dq.published_at = datetime.now(UTC)
        await session.commit()


async def mark_archived(session: AsyncSession, page_id: int) -> None:
    """archive 전환 시 archived_at 갱신."""
    dq = await session.get(DocQuality, page_id)
    if dq is not None:
        dq.archived_at = datetime.now(UTC)
        dq.quadrant = "Q4"
        await session.commit()
