from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from openai import AsyncOpenAI

from kspo_ingest.db.models import LlmUsage
from kspo_ingest.embed import openai_embed
from kspo_ingest.embed.embedder import ChunkToEmbed, embed_chunks


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """tenacity 백오프 0초 — 5xx 재시도 분기도 즉시 진행."""
    monkeypatch.setattr(openai_embed, "RETRY_WAIT_MIN", 0.0)
    monkeypatch.setattr(openai_embed, "RETRY_WAIT_MAX", 0.0)
    yield


@pytest.fixture
def client():
    return AsyncOpenAI(api_key="sk-test-dummy", timeout=10.0, max_retries=0)


def _ok_payload(num: int, prompt_tokens: int) -> dict:
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": [0.01 * i] * 8, "index": i}
            for i in range(num)
        ],
        "model": "text-embedding-3-large",
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


def _items(n: int, *, prefix: str = "chunk") -> list[ChunkToEmbed]:
    return [ChunkToEmbed(chunk_id=i + 1, text=f"{prefix} text {i}") for i in range(n)]


async def test_200_chunks_three_batches(client):
    items = _items(200)

    def handler(request):
        body = json.loads(request.content)
        n = len(body["input"])
        return httpx.Response(200, json=_ok_payload(n, prompt_tokens=10 * n))

    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings").mock(side_effect=handler)
        result = await embed_chunks(
            None, items, model="text-embedding-3-large", job_id=None, client=client
        )

    assert route.call_count == 3
    assert len(result.embedded) == 200
    assert len(result.success_chunk_ids) == 200
    assert result.error_chunk_ids == []
    # 96+96+8 inputs × 10 prompt/input
    assert result.total_prompt_tokens == 2000


async def test_batch_5xx_falls_back_to_singles(client):
    items = _items(96)
    state = {"calls": 0}

    def handler(request):
        state["calls"] += 1
        body = json.loads(request.content)
        n = len(body["input"])
        if n == 96:
            return httpx.Response(503, json={"error": {"type": "server_error"}})
        return httpx.Response(200, json=_ok_payload(n, prompt_tokens=2 * n))

    async with respx.mock(assert_all_called=False) as mock:
        route = mock.post("https://api.openai.com/v1/embeddings").mock(side_effect=handler)
        result = await embed_chunks(
            None, items, model="text-embedding-3-large", job_id=None, client=client
        )

    # 배치 5회 재시도 모두 503 → 96회 단건 호출
    assert route.call_count == openai_embed.RETRY_MAX_ATTEMPTS + 96
    assert len(result.embedded) == 96
    assert result.error_chunk_ids == []
    assert result.total_prompt_tokens == 96 * 2


async def test_one_single_fails_others_succeed(client):
    items = _items(96)
    fail_chunk_id = items[42].chunk_id

    def handler(request):
        body = json.loads(request.content)
        n = len(body["input"])
        if n == 96:
            return httpx.Response(503)
        # 단건 — 특정 chunk_id만 영구 실패
        if f" {fail_chunk_id - 1}" in body["input"][0]:  # _items i=42 → chunk_id=43
            return httpx.Response(503)
        return httpx.Response(200, json=_ok_payload(n, prompt_tokens=3))

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/embeddings").mock(side_effect=handler)
        result = await embed_chunks(
            None, items, model="text-embedding-3-large", job_id=None, client=client
        )

    assert len(result.embedded) == 95
    assert result.error_chunk_ids == [fail_chunk_id]
    assert fail_chunk_id not in result.success_chunk_ids


async def test_aggregate_cost_and_tokens_match(client):
    items = _items(10)

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/embeddings").mock(
            side_effect=lambda req: httpx.Response(
                200,
                json=_ok_payload(
                    len(json.loads(req.content)["input"]),
                    prompt_tokens=1000,
                ),
            )
        )
        result = await embed_chunks(
            None, items, model="text-embedding-3-large", job_id=None, client=client
        )

    assert result.total_prompt_tokens == 1000
    # 1000 tokens × $0.130/1M = $0.000130
    assert result.total_cost_usd == Decimal("0.000130")


async def test_session_persists_status_and_llm_usage(client):
    """AsyncMock session: success는 1 update, 실패 0 → execute 1회. add(llm_usage) 1회."""
    items = _items(5)
    session = AsyncMock()
    session.add = MagicMock()  # SQLAlchemy session.add is sync

    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/embeddings").mock(
            side_effect=lambda req: httpx.Response(
                200,
                json=_ok_payload(
                    len(json.loads(req.content)["input"]),
                    prompt_tokens=50,
                ),
            )
        )
        await embed_chunks(
            session,
            items,
            model="text-embedding-3-large",
            job_id=42,
            client=client,
        )

    # success 5건 → execute 1회 (UPDATE chunks SET embed_status=OK)
    assert session.execute.await_count == 1
    # llm_usage 1행 누계 add
    assert session.add.call_count == 1
    added = session.add.call_args.args[0]
    assert isinstance(added, LlmUsage)
    assert added.purpose == "embedding"
    assert added.model == "text-embedding-3-large"
    assert added.prompt_tokens == 50
    assert added.completion_tokens == 0
    # 50 × 0.130 / 1M = 6.5e-6, banker's rounding → 0.000006
    assert added.cost_usd == Decimal("0.000006")
    assert session.commit.await_count == 1


async def test_session_marks_error_for_failed_chunks(client):
    """단건 실패가 발생하면 ERROR update + OK update 각각 실행 → execute 2회."""
    items = _items(2)

    def handler(request):
        body = json.loads(request.content)
        n = len(body["input"])
        if n == 2:
            return httpx.Response(503)
        if " 1" in body["input"][0]:
            return httpx.Response(503)
        return httpx.Response(200, json=_ok_payload(n, prompt_tokens=5))

    session = AsyncMock()
    session.add = MagicMock()
    async with respx.mock(assert_all_called=False) as mock:
        mock.post("https://api.openai.com/v1/embeddings").mock(side_effect=handler)
        result = await embed_chunks(
            session,
            items,
            model="text-embedding-3-large",
            job_id=None,
            client=client,
        )

    assert result.error_chunk_ids == [items[1].chunk_id]
    assert result.success_chunk_ids == [items[0].chunk_id]
    # OK update + ERROR update
    assert session.execute.await_count == 2


async def test_empty_input_returns_zero_result():
    result = await embed_chunks(
        None, [], model="text-embedding-3-large", job_id=None, client=MagicMock()
    )
    assert result.embedded == []
    assert result.total_prompt_tokens == 0
    assert result.total_cost_usd == Decimal("0")
