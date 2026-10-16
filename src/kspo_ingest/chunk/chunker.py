from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.chunk.header import (
    AttachmentHeaderInput,
    PageHeaderInput,
    build_attachment_header,
    build_page_header,
)
from kspo_ingest.chunk.ids import chunk_id_sha1, to_qdrant_point_id
from kspo_ingest.chunk.tokens import count_tokens
from kspo_ingest.chunk.window_split import window_split
from kspo_ingest.crawl.storage import refined_path
from kspo_ingest.db.models import Chunk as ChunkRow
from kspo_ingest.settings import settings


@dataclass
class Chunk:
    chunk_index: int
    text: str                     # header + body (Qdrant page_content)
    token_len: int
    chunk_id_sha1: str
    qdrant_point_id: UUID
    is_attachment: bool
    attachment_id: int | None


@dataclass
class ChunkInput:
    page_id: int
    embedding_version: int
    domain_host: str
    title: str | None
    posted_at: datetime | None
    summary: str | None
    body_text: str


def chunk_page(inp: ChunkInput) -> list[Chunk]:
    header = build_page_header(
        PageHeaderInput(
            title=inp.title,
            domain_host=inp.domain_host,
            posted_at=inp.posted_at,
            summary=inp.summary,
        )
    )
    body_tokens = count_tokens(inp.body_text)

    if body_tokens > settings.chunk_long_threshold_tokens:
        bodies = window_split(
            inp.body_text,
            target=settings.chunk_target_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
    else:
        bodies = [inp.body_text]

    out: list[Chunk] = []
    for idx, body in enumerate(bodies):
        text = header + body
        sha1 = chunk_id_sha1(inp.page_id, inp.embedding_version, idx, False, None)
        out.append(
            Chunk(
                chunk_index=idx,
                text=text,
                token_len=count_tokens(text),
                chunk_id_sha1=sha1,
                qdrant_point_id=to_qdrant_point_id(sha1),
                is_attachment=False,
                attachment_id=None,
            )
        )
    return out


@dataclass
class AttachmentChunkInput:
    page_id: int
    attachment_id: int
    embedding_version: int
    file_name: str
    parent_title: str | None
    parent_posted_at: datetime | None
    body_text: str


def chunk_attachment(inp: AttachmentChunkInput) -> list[Chunk]:
    header = build_attachment_header(
        AttachmentHeaderInput(
            file_name=inp.file_name,
            parent_title=inp.parent_title,
            parent_posted_at=inp.parent_posted_at,
        )
    )
    body_tokens = count_tokens(inp.body_text)
    if body_tokens > settings.chunk_long_threshold_tokens:
        bodies = window_split(
            inp.body_text,
            target=settings.chunk_target_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
    else:
        bodies = [inp.body_text]

    out: list[Chunk] = []
    for idx, body in enumerate(bodies):
        text = header + body
        sha1 = chunk_id_sha1(inp.page_id, inp.embedding_version, idx, True, inp.attachment_id)
        out.append(
            Chunk(
                chunk_index=idx,
                text=text,
                token_len=count_tokens(text),
                chunk_id_sha1=sha1,
                qdrant_point_id=to_qdrant_point_id(sha1),
                is_attachment=True,
                attachment_id=inp.attachment_id,
            )
        )
    return out


def write_chunks_jsonl(storage_root: Path, page_id: int, chunks: list[Chunk]) -> Path:
    """디버깅 보존 — storage/refined/{page_id}/chunks.jsonl. 1줄/청크."""
    path = refined_path(storage_root, page_id, "chunks.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for c in chunks:
        lines.append(
            json.dumps(
                {
                    "chunk_index": c.chunk_index,
                    "is_attachment": c.is_attachment,
                    "attachment_id": c.attachment_id,
                    "token_len": c.token_len,
                    "chunk_id_sha1": c.chunk_id_sha1,
                    "qdrant_point_id": str(c.qdrant_point_id),
                    "text": c.text,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def upsert_chunks_meta(
    session: AsyncSession,
    *,
    page_id: int,
    attachment_id: int | None,
    chunks: list[Chunk],
    embedding_model: str = "",
) -> list[int]:
    """chunks 메타를 PENDING 상태로 INSERT … ON CONFLICT DO UPDATE.

    임베딩 본체는 T3.2(Embedder)에서 채움. 본 함수는 token_len/qdrant_point_id 등
    재계산 결과로 메타만 갱신한다. 반환은 행 id 목록(`chunk_index` 순서).
    """
    if not chunks:
        return []

    rows = [
        {
            "chunk_id_sha1": c.chunk_id_sha1,
            "qdrant_point_id": c.qdrant_point_id,
            "page_id": page_id,
            "attachment_id": attachment_id if c.is_attachment else None,
            "is_attachment": c.is_attachment,
            "chunk_index": c.chunk_index,
            "token_len": c.token_len,
            "embedding_model": embedding_model,
            "embedding_version": settings.embedding_version,
            "embed_status": "PENDING",
            "kb_status": "PENDING",
        }
        for c in chunks
    ]

    stmt = pg_insert(ChunkRow).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_chunks_page_ver_idx_attach",
        set_={
            "chunk_id_sha1": stmt.excluded.chunk_id_sha1,
            "qdrant_point_id": stmt.excluded.qdrant_point_id,
            "token_len": stmt.excluded.token_len,
            "embedding_model": stmt.excluded.embedding_model,
            "embed_status": "PENDING",
            "kb_status": "PENDING",
        },
    )
    await session.execute(stmt)
    await session.commit()

    is_att = attachment_id is not None
    current_sha1s = [c.chunk_id_sha1 for c in chunks]
    q = (
        select(ChunkRow.id, ChunkRow.chunk_index)
        .where(
            ChunkRow.page_id == page_id,
            ChunkRow.embedding_version == settings.embedding_version,
            ChunkRow.is_attachment == is_att,
            ChunkRow.chunk_id_sha1.in_(current_sha1s),
        )
        .order_by(ChunkRow.chunk_index)
    )
    if is_att:
        q = q.where(ChunkRow.attachment_id == attachment_id)
    result = await session.execute(q)
    return [row.id for row in result.all()]
