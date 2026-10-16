"""Tests for quality.budget — 비용 추정 + 캐시 + 리포트."""
from __future__ import annotations

from decimal import Decimal

import pytest

from kspo_ingest.quality.budget import (
    BudgetReport,
    CallRecord,
    MOCK_REFINE_RESPONSE,
    ResponseCache,
    RunMode,
    estimate_embed_tokens,
    estimate_page_cost,
    estimate_refine_tokens,
    format_budget_report,
)


class TestEstimateRefineTokens:
    def test_short_body(self):
        prompt, completion = estimate_refine_tokens("제목", "짧은 본문")
        assert prompt > 0
        assert completion > 0

    def test_long_body(self):
        body = "한국어 본문 " * 500
        prompt, completion = estimate_refine_tokens("긴 제목", body)
        assert prompt > 500
        assert completion <= 4000

    def test_no_title(self):
        prompt, _ = estimate_refine_tokens(None, "본문 " * 100)
        assert prompt > 0


class TestEstimateEmbedTokens:
    def test_single_chunk(self):
        tokens = estimate_embed_tokens(["한국어 텍스트 " * 100])
        assert tokens > 0

    def test_multiple_chunks(self):
        chunks = ["청크 " * 100, "두번째 청크 " * 100]
        tokens = estimate_embed_tokens(chunks)
        assert tokens > estimate_embed_tokens([chunks[0]])


class TestEstimatePageCost:
    def test_returns_dict(self):
        cost = estimate_page_cost("제목", "본문 " * 100)
        assert "refine_cost_usd" in cost
        assert "embed_cost_usd" in cost
        assert "total_cost_usd" in cost
        assert cost["total_cost_usd"] > 0

    def test_cost_within_reason(self):
        cost = estimate_page_cost("제목", "한국어 본문 " * 200)
        # 페이지당 $0.01 이하여야 함
        assert cost["total_cost_usd"] < 0.01


class TestResponseCache:
    def test_miss(self):
        cache = ResponseCache()
        assert cache.get("hash1", "refine") is None

    def test_hit(self):
        cache = ResponseCache()
        cache.put("hash1", "refine", {"result": "ok"})
        assert cache.get("hash1", "refine") == {"result": "ok"}

    def test_different_purpose(self):
        cache = ResponseCache()
        cache.put("hash1", "refine", {"result": "refine"})
        assert cache.get("hash1", "embedding") is None

    def test_size(self):
        cache = ResponseCache()
        assert cache.size == 0
        cache.put("h1", "refine", {})
        cache.put("h2", "refine", {})
        assert cache.size == 2


class TestBudgetReport:
    def test_initial(self):
        report = BudgetReport(mode="dry_run", budget_usd=5.0)
        assert report.total_calls == 0
        assert report.budget_remaining == 5.0
        assert report.cache_hit_rate == 0.0

    def test_add_call(self):
        report = BudgetReport(mode="dry_run", budget_usd=5.0)
        report.add_call(CallRecord(
            url="https://example.com", content_hash="abc",
            purpose="refine", model="gpt-5.4-mini",
            prompt_tokens=1000, completion_tokens=200,
            cost_usd=0.001, cached=False, mock=True,
        ))
        assert report.total_calls == 1
        assert report.total_prompt_tokens == 1000
        assert report.total_cost_usd == 0.001
        assert report.mock_calls == 1

    def test_cache_hit_rate(self):
        report = BudgetReport(mode="dry_run", budget_usd=5.0)
        report.add_call(CallRecord(
            url="u1", content_hash="h1", purpose="refine", model="m",
            prompt_tokens=0, completion_tokens=0, cost_usd=0,
            cached=True, mock=False,
        ))
        report.add_call(CallRecord(
            url="u2", content_hash="h2", purpose="refine", model="m",
            prompt_tokens=100, completion_tokens=50, cost_usd=0.001,
            cached=False, mock=False,
        ))
        assert report.cache_hit_rate == 0.5

    def test_budget_remaining(self):
        report = BudgetReport(mode="budget", budget_usd=5.0)
        report.add_call(CallRecord(
            url="u", content_hash="h", purpose="refine", model="m",
            prompt_tokens=100, completion_tokens=50, cost_usd=1.5,
            cached=False, mock=False,
        ))
        assert report.budget_remaining == 3.5


class TestFormatReport:
    def test_produces_text(self):
        report = BudgetReport(mode="dry_run", budget_usd=5.0)
        report.documents_tested = 10
        text = format_budget_report(report)
        assert "Budget" in text
        assert "$5.00" in text


class TestMockResponse:
    def test_has_required_fields(self):
        assert "refined_text" in MOCK_REFINE_RESPONSE
        assert "is_meaningful" in MOCK_REFINE_RESPONSE
        assert "summary" in MOCK_REFINE_RESPONSE
        assert "keywords" in MOCK_REFINE_RESPONSE
