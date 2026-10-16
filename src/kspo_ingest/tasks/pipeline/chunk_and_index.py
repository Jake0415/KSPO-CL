"""chunk_and_index — refine 직후 호출되는 M3 결선 task.

흐름: refined_text → chunk_page → upsert chunks meta(PENDING) → embed_chunks(96 batch +
fallback) → build payload → adapter.replace_page_chunks → kb_status=OK + pages.INDEXED.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.chunk.chunker import (
    ChunkInput,
    chunk_page,
    upsert_chunks_meta,
    write_chunks_jsonl,
)
from kspo_ingest.db.models import Chunk as ChunkRow
from kspo_ingest.db.models import Domain, Page
from kspo_ingest.embed.embedder import ChunkToEmbed, embed_chunks
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter, QdrantPoint
from kspo_ingest.qdrant.payload import PayloadInput, build_payload
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled

log = get_logger("worker", "chunk_and_index")


async def chunk_and_index(
    ctx: dict,
    *,
    job_id: int,
    page_id: int,
    refined_text: str,
    summary: str | None,
    keywords: list[str],
    quality_score: float = 0.0,
    quadrant: str = "Q2",
    freshness_score: float = 0.0,
    trust_score: float = 1.0,
    collections: list[str] | None = None,
) -> int:
    """페이지 1건을 청킹→임베딩→Qdrant upsert→INDEXED까지 결선. 반환: indexed 청크 수."""
    session_factory = ctx["session_factory"]
    storage_root = ctx["storage_root"]

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return 0

        page = await s.get(Page, page_id)
        if page is None:
            log.bind(event="chunk_index_no_page", page_id=page_id).warning("page missing")
            return 0
        domain = await s.get(Domain, page.domain_id)
        if domain is None:
            log.bind(event="chunk_index_no_domain", page_id=page_id).warning("domain missing")
            return 0

        # posted_at: clean 단계에서 HTML 메타태그/게시일 추출 → Page에 저장됨.
        posted_at = getattr(page, "posted_at", None)
        chunks = chunk_page(
            ChunkInput(
                page_id=page_id,
                embedding_version=settings.embedding_version,
                domain_host=domain.host,
                title=page.title,
                posted_at=posted_at,
                summary=summary,
                body_text=refined_text,
            )
        )
        if not chunks:
            log.bind(event="chunk_index_empty", page_id=page_id).info("no chunks produced")
            return 0

        write_chunks_jsonl(storage_root, page_id, chunks)

        chunk_ids = await upsert_chunks_meta(
            s,
            page_id=page_id,
            attachment_id=None,
            chunks=chunks,
            embedding_model=settings.openai_embed_model,
        )

    # Embed the full header+body text. Embedding on summary+body only (org-name
    # header stripped) was evaluated to sharpen dense discrimination for a few
    # buried-fact queries (민원), but a full-suite regression test showed it NET
    # REGRESSED more queries (the title/summary header is useful retrieval context
    # for most questions, e.g. 대표자 이름·부서별 업무), so it was reverted.
    items = [
        ChunkToEmbed(chunk_id=cid, text=c.text)
        for cid, c in zip(chunk_ids, chunks, strict=False)
    ]

    async with session_factory() as s:
        embed_result = await embed_chunks(
            s,
            items,
            model=settings.openai_embed_model,
            job_id=job_id,
        )

    if not embed_result.embedded:
        log.bind(
            event="chunk_index_embed_all_failed",
            page_id=page_id,
            errors=len(embed_result.error_chunk_ids),
        ).warning("all chunks failed to embed")
        return 0

    chunk_id_to_chunk = dict(zip(chunk_ids, chunks, strict=False))
    points: list[QdrantPoint] = []
    for emb in embed_result.embedded:
        c = chunk_id_to_chunk[emb.chunk_id]
        payload = build_payload(
            PayloadInput(
                chunk_id_sha1=c.chunk_id_sha1,
                text_with_header=c.text,
                source_url=page.url,
                domain_host=domain.host,
                title=page.title,
                summary=summary,
                keywords=keywords,
                posted_at=posted_at,
                is_attachment=False,
                attachment_id=None,
                attachment_name=None,
                attachment_download_url=None,
                parent_page_id=None,
                parent_page_url=None,
                embedding_version=settings.embedding_version,
                quality_score=quality_score,
                quadrant=quadrant,
                freshness_score=freshness_score,
                trust_score=trust_score,
            )
        )
        points.append(
            QdrantPoint(qdrant_point_id=c.qdrant_point_id, vector=emb.vector, payload=payload)
        )

    adapter = QdrantDirectAdapter()

    # Multi-collection upsert: 같은 벡터를 여러 컬렉션에 (임베딩 1회, upsert N회)
    if collections:
        for col in collections:
            await adapter.upsert_to(col, points)
        upserted_count = len(points)
        deleted_count = 0
    else:
        # 기존 동작: 기본 컬렉션에 replace_page_chunks
        async with session_factory() as s:
            sync = await adapter.replace_page_chunks(
                s,
                page_id=page_id,
                embedding_version=settings.embedding_version,
                new_points=points,
            )
        upserted_count = sync.upserted
        deleted_count = sync.deleted

    async with session_factory() as s:
        await _mark_indexed(s, page_id=page_id, success_chunk_ids=embed_result.success_chunk_ids)
        await bump_stats(s, job_id, indexed=1)

    log.bind(
        event="chunk_index_ok",
        page_id=page_id,
        chunks=len(chunks),
        upserted=upserted_count,
        deleted=deleted_count,
        collections=collections or [adapter.collection],
        errors=len(embed_result.error_chunk_ids),
    ).info("indexed")
    return upserted_count


async def _mark_indexed(
    session: AsyncSession, *, page_id: int, success_chunk_ids: list[int]
) -> None:
    """성공한 청크의 kb_status='OK', 페이지 INDEXED + last_indexed_at."""
    if success_chunk_ids:
        rows = await session.execute(
            select(ChunkRow).where(ChunkRow.id.in_(success_chunk_ids))
        )
        for row in rows.scalars():
            row.kb_status = "OK"

    page = await session.get(Page, page_id)
    if page is not None:
        page.status = "INDEXED"
        page.last_indexed_at = datetime.now(UTC)

    await session.commit()
