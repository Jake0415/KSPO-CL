from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.asyncio import Redis
from redis.exceptions import LockNotOwnedError

from kspo_ingest.tasks import jobs
from kspo_ingest.tasks.pipeline import parallel


@pytest.mark.asyncio
@pytest.mark.parametrize("stats,expected", [
    ({"fetched": 368, "pending_urls": 0, "termination_reason": "queue_exhausted", "collection_partial": True, "errors": 360}, "SUCCESS"),
    ({"fetched": 10, "pending_urls": 0, "termination_reason": "queue_exhausted", "processing_failed": 1}, "SUCCESS"),
    ({"fetched": 0, "pending_urls": 0, "termination_reason": "queue_exhausted", "errors": 1}, "FAILED"),
    ({"fetched": 1, "pending_urls": 5, "termination_reason": "url_limit"}, "FAILED"),
    ({"fetched": 1, "processing_failed": 1}, "FAILED"),
])
async def test_completion_rule(monkeypatch, stats, expected):
    original = dict(stats)
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(stats=stats)))
    finish = AsyncMock()
    monkeypatch.setattr(jobs, "finish_job", finish)
    await jobs.finish_crawl_job(session, 21)
    assert finish.await_args.kwargs["status"] == expected
    assert stats == original


@pytest.mark.asyncio
async def test_expired_lock_cleanup_does_not_fail_completed_collection(monkeypatch):
    redis = MagicMock(spec=Redis)
    lock = SimpleNamespace(acquire=AsyncMock(return_value=True),
                           release=AsyncMock(side_effect=LockNotOwnedError("expired")))
    redis.lock.return_value = lock
    async with parallel.processing_scope({"redis": redis}, 21, 8):
        pass
    lock.release.assert_awaited_once()


@pytest.mark.asyncio
async def test_existing_lock_still_blocks_duplicate_collection():
    redis = MagicMock(spec=Redis)
    lock = SimpleNamespace(acquire=AsyncMock(return_value=False), release=AsyncMock())
    redis.lock.return_value = lock
    with pytest.raises(RuntimeError, match="Another collection"):
        async with parallel.processing_scope({"redis": redis}, 21, 8):
            pass
    lock.release.assert_not_awaited()
