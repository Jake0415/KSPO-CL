from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kspo_ingest.refine.refiner import refine_page


def _mock_response(*, prompt_tokens: int = 100, completion_tokens: int = 50):
    """provider.chat_completion()이 반환할 mock 응답 객체."""
    content = json.dumps(
        {
            "refined_text": "정제된 본문 내용입니다.",
            "is_meaningful": True,
            "summary": "요약 1문장. 요약 2문장.",
            "keywords": ["KSPO", "공고", "2026"],
        },
        ensure_ascii=False,
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


@pytest.mark.asyncio
async def test_refine_drops_short_without_calling_provider():
    mock_provider = MagicMock()
    mock_provider.model = "gpt-5.4-mini"

    with patch("kspo_ingest.refine.refiner.get_provider", return_value=mock_provider):
        r = await refine_page(title="제목", body_text="짧은 본문.")
    assert r.drop is True
    assert r.drop_reason == "too_short"
    mock_provider.chat_completion.assert_not_called()


@pytest.mark.asyncio
async def test_refine_calls_provider_with_json_schema():
    body = "본문이 충분히 길고 한국어 비율도 높은 페이지입니다. " * 10

    mock_provider = MagicMock()
    mock_provider.model = "gpt-5.4-mini"
    mock_provider.chat_completion = AsyncMock(return_value=_mock_response())

    with patch("kspo_ingest.refine.refiner.get_provider", return_value=mock_provider):
        r = await refine_page(title="공고", body_text=body)

    assert r.drop is False
    assert r.refined is not None
    assert r.refined.is_meaningful is True
    assert r.usage is not None
    assert r.usage.total_tokens == 150

    # chat_completion 호출 인자 검증 — response_format json_schema strict
    call_kwargs = mock_provider.chat_completion.call_args[1]
    assert call_kwargs["response_format"]["type"] == "json_schema"
    assert call_kwargs["response_format"]["json_schema"]["strict"] is True
    assert call_kwargs["temperature"] == 0.0
    # 시스템 프롬프트 + 유저 프롬프트
    messages = call_kwargs["messages"]
    assert any(m["role"] == "system" for m in messages)
    assert any(m["role"] == "user" for m in messages)


@pytest.mark.asyncio
async def test_refine_drops_english_majority_without_provider():
    mock_provider = MagicMock()
    mock_provider.model = "gpt-5.4-mini"
    mock_provider.chat_completion = AsyncMock(return_value=_mock_response())

    with patch("kspo_ingest.refine.refiner.get_provider", return_value=mock_provider):
        body = "english only paragraph " * 20
        r = await refine_page(title="Notice", body_text=body)
    assert r.drop is True
    assert r.drop_reason == "english_majority"
    mock_provider.chat_completion.assert_not_awaited()
