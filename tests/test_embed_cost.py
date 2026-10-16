from __future__ import annotations

from decimal import Decimal

from kspo_ingest.embed.cost import calc_embed_cost_usd
from kspo_ingest.refine.cost import PRICING_USD_PER_1M


def test_text_embedding_3_large_per_1m_tokens():
    """1_000_000 tokens × $0.130/1M = $0.130000."""
    cost = calc_embed_cost_usd("text-embedding-3-large", 1_000_000)
    assert cost == Decimal("0.130000")


def test_unknown_model_returns_zero():
    cost = calc_embed_cost_usd("unknown-embed-xxx", 12345)
    assert cost == Decimal("0")


def test_zero_tokens_zero_cost():
    cost = calc_embed_cost_usd("text-embedding-3-large", 0)
    assert cost == Decimal("0.000000")


def test_pricing_table_includes_embedding_model():
    """refine/cost.py와 공유하는 PRICING_USD_PER_1M에 임베딩 모델 등록 필수."""
    assert "text-embedding-3-large" in PRICING_USD_PER_1M
    assert PRICING_USD_PER_1M["text-embedding-3-large"]["completion"] == 0.0


def test_cost_quantized_to_6_decimals():
    cost = calc_embed_cost_usd("text-embedding-3-large", 7)
    assert cost.as_tuple().exponent == -6
