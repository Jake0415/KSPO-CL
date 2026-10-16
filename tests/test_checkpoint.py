"""Tests for crawl.checkpoint — Crawl checkpoint/resume."""
from __future__ import annotations

import pytest
import fakeredis.aioredis

from kspo_ingest.crawl.checkpoint import CheckpointManager, CrawlCheckpoint


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def mgr(redis):
    return CheckpointManager(redis)


class TestCrawlCheckpoint:
    def test_serialize_roundtrip(self):
        cp = CrawlCheckpoint(
            job_id=1, domain_id=2, processed_count=100,
            last_url="https://example.com/page", frontier_size=50,
            created_at=1000.0, status="paused",
        )
        json_str = cp.to_json()
        restored = CrawlCheckpoint.from_json(json_str)
        assert restored.job_id == 1
        assert restored.domain_id == 2
        assert restored.processed_count == 100
        assert restored.last_url == "https://example.com/page"
        assert restored.status == "paused"


class TestCheckpointManager:
    @pytest.mark.asyncio
    async def test_save_and_load(self, mgr):
        cp = await mgr.create(
            job_id=42, domain_id=1,
            processed_count=50, last_url="https://example.com",
            frontier_size=100,
        )
        loaded = await mgr.load(42)
        assert loaded is not None
        assert loaded.job_id == 42
        assert loaded.processed_count == 50

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, mgr):
        loaded = await mgr.load(999)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_exists(self, mgr):
        assert not await mgr.exists(42)
        await mgr.create(
            job_id=42, domain_id=1,
            processed_count=0, last_url="",
            frontier_size=0,
        )
        assert await mgr.exists(42)

    @pytest.mark.asyncio
    async def test_delete(self, mgr):
        await mgr.create(
            job_id=42, domain_id=1,
            processed_count=0, last_url="",
            frontier_size=0,
        )
        await mgr.delete(42)
        assert not await mgr.exists(42)

    @pytest.mark.asyncio
    async def test_list_all(self, mgr):
        await mgr.create(job_id=1, domain_id=1, processed_count=10, last_url="a", frontier_size=5)
        await mgr.create(job_id=2, domain_id=2, processed_count=20, last_url="b", frontier_size=3)
        all_cps = await mgr.list_all()
        assert len(all_cps) == 2
        ids = {cp.job_id for cp in all_cps}
        assert ids == {1, 2}
