from __future__ import annotations

import httpx
import pytest
import respx
from openai import APIStatusError, AsyncOpenAI, AuthenticationError

from kspo_ingest.embed import openai_embed
from kspo_ingest.embed.openai_embed import embed_batch


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """tenacity 백오프를 0초로 — 재시도 분기 테스트 가속."""
    monkeypatch.setattr(openai_embed, "RETRY_WAIT_MIN", 0.0)
    monkeypatch.setattr(openai_embed, "RETRY_WAIT_MAX", 0.0)
    yield


@pytest.fixture
def client():
    return AsyncOpenAI(api_key="sk-test-dummy", timeout=10.0, max_retries=0)


def _ok_payload(num: int, prompt_tokens: int = 100) -> dict:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": [float(i) / 10] * 8, "index": i}
            for i in range(num)
        ],
        "model": "text-embedding-3-large",
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


async def test_embed_batch_returns_vectors_in_order(client):
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(200, json=_ok_payload(2, prompt_tokens=120))
        )
        r = await embed_batch(client, "text-embedding-3-large", ["a", "b"])
    assert len(r.vectors) == 2
    assert r.vectors[0][0] == 0.0
    assert r.vectors[1][0] == pytest.approx(0.1)
    assert r.prompt_tokens == 120
    assert r.total_tokens == 120


async def test_embed_batch_retries_on_5xx_then_succeeds(client):
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings")
        route.side_effect = [
            httpx.Response(503, json={"error": {"type": "server_error"}}),
            httpx.Response(200, json=_ok_payload(1, prompt_tokens=10)),
        ]
        r = await embed_batch(client, "text-embedding-3-large", ["x"])
    assert route.call_count == 2
    assert len(r.vectors) == 1


async def test_embed_batch_retries_on_429(client):
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings")
        route.side_effect = [
            httpx.Response(429, json={"error": {"type": "rate_limit_exceeded"}}),
            httpx.Response(200, json=_ok_payload(1, prompt_tokens=5)),
        ]
        r = await embed_batch(client, "text-embedding-3-large", ["q"])
    assert route.call_count == 2
    assert r.prompt_tokens == 5


async def test_embed_batch_does_not_retry_on_401(client):
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(401, json={"error": {"type": "invalid_api_key"}})
        )
        with pytest.raises(AuthenticationError):
            await embed_batch(client, "text-embedding-3-large", ["q"])
    assert route.call_count == 1


async def test_embed_batch_gives_up_after_max_attempts(client, monkeypatch):
    """5xx가 5회 연속이면 마지막에 raise."""
    monkeypatch.setattr(openai_embed, "RETRY_MAX_ATTEMPTS", 3)
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings").mock(
            return_value=httpx.Response(503, json={"error": {"type": "server_error"}})
        )
        with pytest.raises(APIStatusError):
            await embed_batch(client, "text-embedding-3-large", ["x"])
    assert route.call_count == 3
