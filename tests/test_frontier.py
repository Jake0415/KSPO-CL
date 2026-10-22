from __future__ import annotations

import fakeredis.aioredis
import pytest
import pytest_asyncio

from kspo_ingest.crawl.frontier import Frontier


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    try:
        yield r
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_enqueue_dedup_via_seen(redis):
    f = Frontier(redis)
    assert await f.enqueue(1, "https://x.com/a", 0) is True
    assert await f.enqueue(1, "https://x.com/a", 5) is False  # 동일 url_hash → 거부


@pytest.mark.asyncio
async def test_enqueue_dedup_via_normalize(redis):
    """다른 형태지만 정규화 후 동일 — 중복 차단."""
    f = Frontier(redis)
    assert await f.enqueue(1, "HTTPS://X.com/a?utm_source=x", 0) is True
    assert await f.enqueue(1, "https://x.com/a", 1) is False


@pytest.mark.asyncio
async def test_dequeue_returns_in_order(redis):
    f = Frontier(redis)
    await f.enqueue(1, "https://x.com/1", 0)
    await f.enqueue(1, "https://x.com/2", 0)
    await f.enqueue(1, "https://x.com/3", 0)

    first = await f.dequeue(1)
    second = await f.dequeue(1)
    third = await f.dequeue(1)
    fourth = await f.dequeue(1)

    assert first is not None and first[0].endswith("/1")
    assert second is not None and second[0].endswith("/2")
    assert third is not None and third[0].endswith("/3")
    assert fourth is None


@pytest.mark.asyncio
async def test_dequeue_records_inflight(redis):
    f = Frontier(redis)
    await f.enqueue(1, "https://x.com/a", 0)
    url, _ = await f.dequeue(1)
    members = await redis.smembers("inflight:1")
    assert len(members) == 1
    await f.ack(1, url)
    members = await redis.smembers("inflight:1")
    assert len(members) == 0


@pytest.mark.asyncio
async def test_jobs_isolated(redis):
    f = Frontier(redis)
    await f.enqueue(1, "https://x.com/a", 0)
    await f.enqueue(2, "https://x.com/a", 0)
    s1 = await f.size(1)
    s2 = await f.size(2)
    assert s1 == 1 and s2 == 1


@pytest.mark.asyncio
async def test_size_decreases_on_dequeue(redis):
    f = Frontier(redis)
    await f.enqueue(1, "https://x.com/a", 0)
    await f.enqueue(1, "https://x.com/b", 0)
    assert await f.size(1) == 2
    await f.dequeue(1)
    assert await f.size(1) == 1


@pytest.mark.asyncio
async def test_hard_url_limit_and_duplicate_counter(redis):
    f = Frontier(redis)
    await redis.set("crawl_limit:1", 2000)
    for n in range(2000):
        assert await f.enqueue(1, f"https://x.com/{n}", 0)
    assert not await f.enqueue(1, "https://x.com/overflow", 0)
    assert await redis.scard("seen:1") == 2000
    assert await f.size(1) == 2000
    assert await redis.get("url_limit:1") == b"1"
    assert not await f.enqueue(1, "https://x.com/0", 0)
    assert await redis.get("duplicates:1") == b"1"
    assert await f.enqueue(2, "https://x.com/overflow", 0)


@pytest.mark.asyncio
async def test_board_direct_admission_shares_url_budget(redis):
    f = Frontier(redis)
    assert await f.enqueue(1, "https://x.com/root", 0)
    assert await f.admit_direct(1, "https://x.com/board/1", limit=2)
    assert not await f.admit_direct(1, "https://x.com/board/2", limit=2)
    assert await f.admit_direct(1, "https://x.com/board/1", limit=2)
    assert await f.size(1) == 1
    assert await redis.scard("seen:1") == 2
