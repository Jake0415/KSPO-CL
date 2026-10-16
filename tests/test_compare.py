from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kspo_ingest.evaluation.compare import ComparisonResult, compare_providers
from kspo_ingest.refine.provider import reset_providers


@pytest.fixture(autouse=True)
def _mock_settings(monkeypatch):
    monkeypatch.setattr("kspo_ingest.settings.settings.openai_api_key", "test-key")
    monkeypatch.setattr("kspo_ingest.settings.settings.gemini_api_key", "test-key")
    reset_providers()
    yield
    reset_providers()


@pytest.mark.asyncio
async def test_compare_providers_returns_results():
    test_cases = [
        {"title": "테스트 제목", "body_text": "이것은 테스트 본문입니다. 한국어 콘텐츠 내용이 충분히 길어야 합니다."},
    ]

    mock_case_result = MagicMock()
    mock_case_result.cost_usd = 0.001
    mock_case_result.latency_ms = 500.0
    mock_case_result.is_meaningful = True
    mock_case_result.dropped = False

    with patch(
        "kspo_ingest.evaluation.compare.refine_with_provider",
        new_callable=AsyncMock,
        return_value=mock_case_result,
    ):
        results = await compare_providers(
            test_cases=test_cases,
            provider_names=["openai", "gemini"],
        )

    assert len(results) == 2
    assert all(isinstance(r, ComparisonResult) for r in results)
    assert results[0].provider_name == "openai"
    assert results[1].provider_name == "gemini"
    assert results[0].total_cost_usd > 0
    assert results[0].avg_latency_ms > 0


@pytest.mark.asyncio
async def test_compare_handles_provider_error():
    test_cases = [
        {"title": "Test", "body_text": "Content that is long enough for processing."},
    ]

    with patch(
        "kspo_ingest.evaluation.compare.refine_with_provider",
        new_callable=AsyncMock,
        side_effect=Exception("API error"),
    ):
        results = await compare_providers(
            test_cases=test_cases,
            provider_names=["openai"],
        )

    assert len(results) == 1
    assert results[0].cases[0].dropped is True
