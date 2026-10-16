from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kspo_ingest.refine.refiner import refine_page


@pytest.mark.asyncio
async def test_refine_page_uses_provider(monkeypatch):
    """refine_page should use get_provider() instead of hardcoded OpenAI."""
    monkeypatch.setattr("kspo_ingest.settings.settings.ko_ratio_threshold", 0.0)

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"refined_text":"refined","is_meaningful":true,"summary":"s","keywords":["k"]}'
            )
        )
    ]
    mock_response.usage = MagicMock(
        prompt_tokens=10, completion_tokens=20, total_tokens=30
    )

    mock_provider = MagicMock()
    mock_provider.name = "openai"
    mock_provider.model = "gpt-5.4-mini"
    mock_provider.chat_completion = AsyncMock(return_value=mock_response)

    with patch(
        "kspo_ingest.refine.refiner.get_provider",
        return_value=mock_provider,
    ):
        result = await refine_page(
            title="Test",
            body_text="한국어 콘텐츠 테스트를 위한 충분히 긴 본문입니다. 이 텍스트는 사전 규칙의 최소 길이 요구사항을 충족하기 위해 작성되었습니다. 추가 텍스트를 포함하여 백 자 이상이 되도록 늘립니다. 충분한 길이의 한국어 텍스트입니다.",
        )

    assert not result.drop
    assert result.model == "gpt-5.4-mini"
    mock_provider.chat_completion.assert_called_once()
