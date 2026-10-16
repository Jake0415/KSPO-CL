"""Crawl checkpoint — 크롤 상태 저장/복원으로 pause/resume 지원.

Scrapling의 checkpoint 개념을 Redis 기반으로 구현.
체크포인트: frontier 상태 + 처리된 URL 수 + 마지막 처리 URL.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "checkpoint")


@dataclass
class CrawlCheckpoint:
    job_id: int
    domain_id: int
    processed_count: int
    last_url: str
    frontier_size: int
    created_at: float
    status: str  # "paused" | "completed" | "failed"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> CrawlCheckpoint:
        return cls(**json.loads(raw))


class CheckpointManager:
    """Redis 기반 체크포인트 관리.

    사용법:
        mgr = CheckpointManager(redis)
        await mgr.save(checkpoint)
        restored = await mgr.load(job_id)
        await mgr.delete(job_id)
    """

    KEY_PREFIX = "checkpoint"

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def _key(self, job_id: int) -> str:
        return f"{self.KEY_PREFIX}:{job_id}"

    async def save(self, checkpoint: CrawlCheckpoint) -> None:
        key = self._key(checkpoint.job_id)
        await self._redis.set(key, checkpoint.to_json(), ex=86400 * 7)  # 7일 TTL
        log.bind(
            event="checkpoint_saved",
            job_id=checkpoint.job_id,
            processed=checkpoint.processed_count,
        ).info("checkpoint saved")

    async def load(self, job_id: int) -> CrawlCheckpoint | None:
        key = self._key(job_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return CrawlCheckpoint.from_json(raw)

    async def delete(self, job_id: int) -> None:
        await self._redis.delete(self._key(job_id))

    async def exists(self, job_id: int) -> bool:
        return bool(await self._redis.exists(self._key(job_id)))

    async def create(
        self,
        *,
        job_id: int,
        domain_id: int,
        processed_count: int,
        last_url: str,
        frontier_size: int,
        status: str = "paused",
    ) -> CrawlCheckpoint:
        cp = CrawlCheckpoint(
            job_id=job_id,
            domain_id=domain_id,
            processed_count=processed_count,
            last_url=last_url,
            frontier_size=frontier_size,
            created_at=time.time(),
            status=status,
        )
        await self.save(cp)
        return cp

    async def list_all(self) -> list[CrawlCheckpoint]:
        """모든 체크포인트 조회."""
        pattern = f"{self.KEY_PREFIX}:*"
        checkpoints: list[CrawlCheckpoint] = []
        async for key in self._redis.scan_iter(match=pattern):
            raw = await self._redis.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode()
                checkpoints.append(CrawlCheckpoint.from_json(raw))
        return checkpoints
