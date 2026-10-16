from __future__ import annotations

from decimal import Decimal

from kspo_ingest.refine.cost import PRICING_USD_PER_1M, calc_cost_usd


def test_known_model_calc():
    """gpt-5.4-mini: prompt 0.15, completion 0.60 USD per 1M tokens.

    1000 prompt + 500 completion = (1000*0.15 + 500*0.60) / 1_000_000 = 0.00045
    """
    cost = calc_cost_usd("gpt-5.4-mini", prompt_tokens=1000, completion_tokens=500)
    assert cost == Decimal("0.000450")


def test_embedding_model_input_only():
    """text-embedding-3-large: prompt 0.130 / completion 0 — input only.

    1_000_000 tokens → $0.130
    """
    cost = calc_cost_usd("text-embedding-3-large", prompt_tokens=1_000_000, completion_tokens=0)
    assert cost == Decimal("0.130000")


def test_unknown_model_uses_fallback_rate():
    """미등록 모델은 가장 비싼 요율(1.250/10.000)로 보수적 추정."""
    cost = calc_cost_usd("unknown-model-xxx", prompt_tokens=1000, completion_tokens=500)
    # (1000 * 1.250 + 500 * 10.000) / 1_000_000 = 6250 / 1_000_000 = 0.006250
    assert cost == Decimal("0.006250")


def test_pricing_table_has_required_models():
    assert "gpt-5.4-mini" in PRICING_USD_PER_1M
    assert "text-embedding-3-large" in PRICING_USD_PER_1M


def test_zero_tokens_zero_cost():
    cost = calc_cost_usd("gpt-5.4-mini", prompt_tokens=0, completion_tokens=0)
    assert cost == Decimal("0.000000")


def test_decimal_precision_6():
    """결과는 항상 6자리 소수점 quantize."""
    cost = calc_cost_usd("gpt-5.4-mini", prompt_tokens=1, completion_tokens=1)
    # exponent는 -6
    assert cost.as_tuple().exponent == -6
