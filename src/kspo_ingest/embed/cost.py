from __future__ import annotations

from decimal import Decimal

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.cost import PRICING_USD_PER_1M

log = get_logger("embed", "cost")


def calc_embed_cost_usd(model: str, prompt_tokens: int) -> Decimal:
    """임베딩은 input only — completion=0. 미등록 모델은 0 + WARN."""
    rate = PRICING_USD_PER_1M.get(model)
    if rate is None:
        log.bind(event="model_pricing_missing", model=model).warning(
            "PRICING_USD_PER_1M에 임베딩 모델 가격 미등록 — cost=0 처리"
        )
        return Decimal("0")
    cost = Decimal(prompt_tokens) * Decimal(str(rate["prompt"])) / Decimal("1000000")
    return cost.quantize(Decimal("0.000001"))
