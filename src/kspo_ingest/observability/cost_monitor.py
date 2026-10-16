"""월 LLM 비용 모니터 + 80% 임계 검사.

- 누계: llm_usage 테이블의 cost_usd 합계 × USD_TO_KRW_RATE.
- 임계: settings.openai_monthly_budget_krw × 0.8.
- 1회 발신 보장: Redis `alert:budget80:YYYYMM` 키로 같은 달 중복 발신 차단.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import LlmUsage
from kspo_ingest.settings import settings

_KST = ZoneInfo("Asia/Seoul")


@dataclass
class AlertDecision:
    cost_krw: Decimal
    budget_krw: Decimal
    used_pct: float
    crossed_threshold: bool        # 알림 발신 필요 (80% 첫 도달 + 미발신)
    currently_over: bool           # UI 배너 표시 필요 (현재 80% 이상)


def _first_of_month_kst(now: datetime | None = None) -> datetime:
    n = now or datetime.now(_KST)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_monthly_cost_krw(
    session: AsyncSession, *, now: datetime | None = None
) -> Decimal:
    """이번 달(KST 기준) llm_usage cost_usd 합계 × USD_TO_KRW_RATE."""
    first = _first_of_month_kst(now)
    cost_usd = await session.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.created_at >= first
        )
    )
    cost_usd = Decimal(cost_usd or 0)
    rate = Decimal(str(settings.usd_to_krw_rate))
    return (cost_usd * rate).quantize(Decimal("0.01"))


async def check_budget_threshold(
    session: AsyncSession, *, redis: Redis | None = None, now: datetime | None = None
) -> AlertDecision:
    """80% 임계 도달 판단 + Redis로 1회 발신 보장.

    redis=None이면 1회 발신 보장 없이 판정만 (테스트 편의).
    """
    cost = await get_monthly_cost_krw(session, now=now)
    budget = Decimal(settings.openai_monthly_budget_krw)
    if budget <= 0:
        return AlertDecision(
            cost_krw=cost, budget_krw=budget, used_pct=0.0,
            crossed_threshold=False, currently_over=False,
        )
    threshold = budget * Decimal("0.8")
    used_pct = float(cost / budget * 100)
    currently_over = cost >= threshold

    crossed = False
    if currently_over and redis is not None:
        ts = now or datetime.now(_KST)
        month_key = ts.strftime("alert:budget80:%Y%m")
        already = await redis.exists(month_key)
        if not already:
            # 35일 TTL — 다음 달 reset 보장
            await redis.setex(month_key, 35 * 86_400, "1")
            crossed = True

    return AlertDecision(
        cost_krw=cost,
        budget_krw=budget,
        used_pct=used_pct,
        crossed_threshold=crossed,
        currently_over=currently_over,
    )


async def is_budget_exceeded(session: AsyncSession) -> bool:
    """월 예산 100% 초과 여부. True면 LLM 호출 차단해야 함."""
    cost = await get_monthly_cost_krw(session)
    budget = Decimal(settings.openai_monthly_budget_krw)
    if budget <= 0:
        return False
    return cost >= budget
