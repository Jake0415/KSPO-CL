"""refine_page ARQ task — pre-rule + OpenAI 호출 + llm_usage 기록.

사전 제외 규칙만 적용하며 LLM 의미 판단으로 문서를 제외하지 않는다.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.clean.rag import enriched_content, normalize_text
from kspo_ingest.db.models import Chunk
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
from kspo_ingest.refine.cost import record_llm_usage
from kspo_ingest.refine.refiner import refine_page as do_refine
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled
from kspo_ingest.tasks.pipeline.helpers import mark_dropped, mark_refined

log = get_logger("worker", "refine_page")


async def refine_page(
    ctx: dict, *, job_id: int, page_id: int, title: str | None, body_text: str, content_hash: str
) -> dict | None:
    session_factory = ctx["session_factory"]

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return None

        body_text = normalize_text(body_text)
        result = await do_refine(title=title, body_text=body_text)

        if result.usage is not None:
            await record_llm_usage(
                s,
                page_id=page_id,
                attachment_id=None,
                job_id=job_id,
                purpose="refine",
                model=result.model,
                usage=result.usage,
            )

        if result.drop:
            await _purge_existing_chunks(s, page_id=page_id)
            await mark_dropped(s, page_id, reason=result.drop_reason or "unknown")
            await bump_stats(s, job_id, dropped=1, **{f"drop_reasons__{result.drop_reason}": 1})
            return None

        if result.refined:
            result.refined.is_meaningful = True
            result.refined.refined_text = enriched_content(body_text, result.refined.refined_text)
        await mark_refined(s, page_id, content_hash=content_hash, title=title)
        await bump_stats(s, job_id, refined=1)

        # chunk_and_index 호출은 caller(enqueue_seeds / run_incremental)가 결선.
        return {
            "page_id": page_id,
            "refined": result.refined.model_dump() if result.refined else None,
        }


async def _purge_existing_chunks(session: AsyncSession, *, page_id: int) -> int:
    """page의 기존 청크를 PG + Qdrant 모두 삭제. INDEXED→DROPPED 전환 시 호출.

    Qdrant 실패는 WARN 로그만 남기고 PG 삭제는 수행 — incremental에서 재시도 가능.
    """
    rows = await session.execute(
        select(Chunk.id, Chunk.qdrant_point_id).where(Chunk.page_id == page_id)
    )
    points = rows.all()
    if not points:
        return 0

    point_ids = [r[1] for r in points]
    try:
        await QdrantDirectAdapter().delete_by_ids(point_ids)
    except Exception as exc:  # noqa: BLE001
        log.bind(
            event="refine_purge_qdrant_fail",
            page_id=page_id,
            count=len(point_ids),
            error=type(exc).__name__,
        ).warning(str(exc))

    await session.execute(delete(Chunk).where(Chunk.page_id == page_id))
    await session.commit()
    log.bind(
        event="refine_purge_chunks",
        page_id=page_id,
        count=len(points),
    ).info("existing chunks purged")
    return len(points)
