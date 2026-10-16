"""GET /api/alerts — UI topbar 배너용 active 알림 목록.

UI 측에서 30초 폴링. 현재는 budget_80 알림만 — 향후 KB dim mismatch, OpenAI auth 실패
등 추가 시 본 라우터에 통합.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.observability.cost_monitor import check_budget_threshold

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


class Alert(BaseModel):
    kind: str
    severity: str  # info | warning | error
    message: str
    details: dict[str, Any] = {}


class AlertsOut(BaseModel):
    alerts: list[Alert]


@router.get("", response_model=AlertsOut)
async def list_active_alerts(
    s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> AlertsOut:
    decision = await check_budget_threshold(s, redis=None)
    alerts: list[Alert] = []
    if decision.currently_over:
        alerts.append(
            Alert(
                kind="budget_80",
                severity="warning",
                message=(
                    f"OpenAI 월 누계 {decision.used_pct:.1f}% "
                    "— 한도 임박"
                ),
                details={
                    "cost_krw": str(decision.cost_krw),
                    "budget_krw": str(decision.budget_krw),
                },
            )
        )
    return AlertsOut(alerts=alerts)
