from __future__ import annotations

from decimal import Decimal

from kspo_ingest.refine.cost import calc_cost_usd


def test_calc_cost_openai():
    cost = calc_cost_usd("gpt-5.4-mini", prompt_tokens=1000, completion_tokens=500)
    assert cost > Decimal("0")


def test_calc_cost_gemini_flash():
    cost = calc_cost_usd("gemini-2.5-flash", prompt_tokens=1000, completion_tokens=500)
    assert cost > Decimal("0")


def test_calc_cost_gemini_pro():
    cost = calc_cost_usd("gemini-2.5-pro", prompt_tokens=1000, completion_tokens=500)
    assert cost > Decimal("0")
    # Pro should be more expensive than flash
    flash_cost = calc_cost_usd("gemini-2.5-flash", prompt_tokens=1000, completion_tokens=500)
    assert cost > flash_cost


def test_unknown_model_uses_fallback():
    cost = calc_cost_usd("unknown-model", prompt_tokens=1000, completion_tokens=500)
    assert cost > Decimal("0")  # Should use fallback rate, not zero
