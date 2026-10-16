"""GET /api/pages — Admin UI 페이지 검색·상세."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.api.schemas.page import PageChunkOut, PageDetailOut, PageOut
from kspo_ingest.db.models import Attachment, Chunk, Page

router = APIRouter(prefix="/api/pages", tags=["pages"])


@router.get("", response_model=list[PageOut])
async def list_pages(
    domain_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, description="URL/title 부분 일치 검색"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> list[Page]:
    stmt = select(Page).order_by(Page.id.desc()).limit(limit).offset(offset)
    if domain_id is not None:
        stmt = stmt.where(Page.domain_id == domain_id)
    if status_filter:
        stmt = stmt.where(Page.status == status_filter)
    if q:
        like = f"%{q}%"
        stmt = stmt.where((Page.url.ilike(like)) | (Page.title.ilike(like)))
    rows = (await s.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/{id}", response_model=PageDetailOut)
async def get_page(
    id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> PageDetailOut:
    page = await s.get(Page, id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "page not found")

    chunk_rows = (
        await s.execute(
            select(Chunk).where(Chunk.page_id == id).order_by(Chunk.chunk_index)
        )
    ).scalars().all()
    chunks = [PageChunkOut.model_validate(c) for c in chunk_rows]

    attachments_count = await s.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.page_id == id)
    )

    base = PageOut.model_validate(page).model_dump()
    return PageDetailOut(
        **base, chunks=chunks, attachments_count=int(attachments_count or 0)
    )
