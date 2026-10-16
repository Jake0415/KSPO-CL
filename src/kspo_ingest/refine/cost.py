from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.db.models import LlmUsage
from kspo_ingest.observability.logger import get_logger

log = get_logger("refine", "cost")


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# OpenAI 가격 (USD per 1M tokens). 모델 추가/변경 시 PR로 갱신 (Tier 2: 자동 회수).
PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    # gpt-5.4-mini (예시 가격 — 실제 운영 시 OpenAI 페이지값으로 갱신)
    "gpt-5.4-mini": {"prompt": 0.150, "completion": 0.600},
    # text-embedding-3-large — embedding은 input only
    "text-embedding-3-large": {"prompt": 0.130, "completion": 0.0},
    # Gemini
    "gemini-2.5-flash": {"prompt": 0.150, "completion": 0.600},
    "gemini-2.5-pro": {"prompt": 1.250, "completion": 10.000},
}

# Fallback — 미등록 모델은 가장 비싼 모델 요율로 보수적 추정
_FALLBACK_RATE = {"prompt": 1.250, "completion": 10.000}


def calc_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    rate = PRICING_USD_PER_1M.get(model, _FALLBACK_RATE)
    cost = (
        Decimal(prompt_tokens) * Decimal(str(rate["prompt"]))
        + Decimal(completion_tokens) * Decimal(str(rate["completion"]))
    ) / Decimal("1000000")
    return cost.quantize(Decimal("0.000001"))


async def record_llm_usage(
    session: AsyncSession,
    *,
    page_id: int | None,
    attachment_id: int | None,
    job_id: int | None,
    purpose: Literal["refine", "embedding"],
    model: str,
    usage: TokenUsage,
) -> None:
    cost_usd = calc_cost_usd(model, usage.prompt_tokens, usage.completion_tokens)
    row = LlmUsage(
        page_id=page_id,
        attachment_id=attachment_id,
        job_id=job_id,
        purpose=purpose,
        model=model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        cost_usd=cost_usd,
    )
    session.add(row)
    await session.commit()
