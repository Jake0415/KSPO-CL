from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.db.models import QaLog

router = APIRouter(prefix="/api/qa-logs", tags=["qa-logs"])


class QaLogOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    question: str
    answer: str | None
    sources: dict | list | None
    is_answered: bool
    error_message: str | None
    satisfaction: int | None
    latency_ms: int | None
    provider: str | None
    model: str | None
    created_at: datetime | None


class SatisfactionUpdate(BaseModel):
    satisfaction: int = Field(ge=1, le=5)


@router.get("", response_model=list[QaLogOut])
async def list_qa_logs(
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
    unanswered_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[QaLog]:
    """QA 로그 리스트. unanswered_only=true로 미응답만 필터."""
    stmt = select(QaLog).order_by(QaLog.created_at.desc())
    if unanswered_only:
        stmt = stmt.where(QaLog.is_answered.is_(False))
    stmt = stmt.limit(limit).offset(offset)
    rows = (await s.execute(stmt)).scalars().all()
    return list(rows)


@router.get("/stats")
async def qa_stats(
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> dict:
    """QA 통계 — 총 질의수, 미응답수, 평균 만족도."""
    total = await s.scalar(select(func.count()).select_from(QaLog)) or 0
    unanswered = await s.scalar(
        select(func.count()).select_from(QaLog).where(QaLog.is_answered.is_(False))
    ) or 0
    avg_satisfaction = await s.scalar(
        select(func.avg(QaLog.satisfaction)).where(QaLog.satisfaction.is_not(None))
    )
    return {
        "total": total,
        "unanswered": unanswered,
        "avg_satisfaction": round(float(avg_satisfaction), 2) if avg_satisfaction else None,
    }


@router.post("/{log_id}/satisfaction", status_code=status.HTTP_200_OK)
async def update_satisfaction(
    log_id: int,
    body: SatisfactionUpdate,
    s: AsyncSession = SessionDep,
) -> None:
    """사용자 만족도 기록 (1-5점). 인증 불필요 (챗봇 사용자가 호출)."""
    log_row = await s.get(QaLog, log_id)
    if log_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "qa_log_not_found")
    log_row.satisfaction = body.satisfaction
    await s.commit()
