from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.api.schemas.board_source import BoardSourceCreate, BoardSourceOut
from kspo_ingest.crawl.board_detect import revalidate_source, upsert_board_candidate
from kspo_ingest.db.models import BoardSource, Domain

router = APIRouter(prefix="/api/board-sources", tags=["board-sources"])


@router.get("", response_model=list[BoardSourceOut])
async def list_sources(
    status: str | None = None,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> list[BoardSource]:
    q = select(BoardSource)
    if status:
        q = q.where(BoardSource.status == status)
    q = q.order_by(BoardSource.status, BoardSource.detected_at.desc())
    return list((await s.execute(q)).scalars().all())


@router.post("", response_model=BoardSourceOut, status_code=status.HTTP_201_CREATED)
async def add_source(
    body: BoardSourceCreate,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> BoardSource:
    domain = await s.get(Domain, body.domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="domain not found")
    try:
        src = await upsert_board_candidate(s, domain_id=body.domain_id, list_url=body.list_url)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="게시판 최초 목록 검증 요청 실패") from exc
    if src is None or src.status == "rejected":
        raise HTTPException(status_code=422, detail="검증된 게시판 최초 목록 주소가 아닙니다")
    await s.refresh(src)
    return src


async def _get_or_404(s: AsyncSession, id: int) -> BoardSource:
    src = await s.get(BoardSource, id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return src


@router.post("/{id}/confirm", response_model=BoardSourceOut)
async def confirm_source(
    id: int,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> BoardSource:
    src = await _get_or_404(s, id)
    domain = await s.get(Domain, src.domain_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="domain not found")
    try:
        verified = await revalidate_source(s, src, domain)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="게시판 최초 목록 검증 요청 실패") from exc
    if not verified:
        raise HTTPException(status_code=422, detail=src.validation_error or "invalid board list")
    src.status = "confirmed"
    src.confirmed_at = datetime.now(UTC)
    await s.commit()
    await s.refresh(src)
    return src


@router.post("/{id}/reject", response_model=BoardSourceOut)
async def reject_source(
    id: int,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> BoardSource:
    src = await _get_or_404(s, id)
    src.status = "rejected"
    await s.commit()
    await s.refresh(src)
    return src


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    id: int,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> Response:
    src = await _get_or_404(s, id)
    await s.delete(src)
    await s.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
