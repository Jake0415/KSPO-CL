from __future__ import annotations

import json

from redis.asyncio import Redis

from kspo_ingest.crawl.url_class import is_search_result_url
from kspo_ingest.crawl.url_normalize import normalize_url


class Frontier:
    """Redis 기반 BFS frontier — 단일 worker 가정.

    Keys per job:
      - frontier:{job_id}  List   방문 대기 (RPUSH/LPOP — FIFO)
      - seen:{job_id}      Set    등록된 url_hash (중복 차단)
      - inflight:{job_id}  Set    처리 중 url_hash
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def enqueue(self, job_id: int, url: str, depth: int) -> bool:
        """url을 정규화 후 frontier에 push. 이미 seen에 있으면 False."""
        if is_search_result_url(url):
            return False
        normalized, url_hash = normalize_url(url)
        limit = int(await self.redis.get(f"crawl_limit:{job_id}") or 30000)
        if not await self.reserve_discovery(job_id, normalized, limit=limit):
            return False
        added = await self.redis.eval(
            """
            if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then
                redis.call('INCR', KEYS[3]); return 0
            end
            local limit = tonumber(redis.call('GET', KEYS[5]) or '30000')
            if redis.call('SCARD', KEYS[1]) >= limit then
                redis.call('SET', KEYS[4], '1'); return 0
            end
            redis.call('SADD', KEYS[1], ARGV[1])
            redis.call('RPUSH', KEYS[2], ARGV[2]); return 1
        """,
            5,
            self._k_seen(job_id),
            self._k_frontier(job_id),
            f"duplicates:{job_id}",
            f"url_limit:{job_id}",
            f"crawl_limit:{job_id}",
            url_hash,
            json.dumps({"url": normalized, "depth": depth}),
        )
        return bool(added)

    async def admit_direct(self, job_id: int, url: str, *, limit: int = 30000) -> bool:
        """Reserve a board URL under the same full-job unique URL budget."""
        if not await self.reserve_discovery(job_id, url, limit=limit):
            return False
        _, url_hash = normalize_url(url)
        return bool(
            await self.redis.eval(
                """
            if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 1 end
            if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
                redis.call('SET', KEYS[2], '1'); return 0
            end
            redis.call('SADD', KEYS[1], ARGV[1]); return 1
        """,
                2,
                self._k_seen(job_id),
                f"url_limit:{job_id}",
                url_hash,
                str(min(limit, 30000)),
            )
        )

    async def reserve_discovery(self, job_id: int, url: str, *, limit: int) -> bool:
        """Atomically admit URLs before DB insert, including not-yet-queued links."""
        if is_search_result_url(url):
            return False
        _, url_hash = normalize_url(url)
        return bool(
            await self.redis.eval(
                """
            if redis.call('SISMEMBER', KEYS[1], ARGV[1]) == 1 then return 1 end
            if redis.call('SCARD', KEYS[1]) >= tonumber(ARGV[2]) then
                redis.call('SET', KEYS[2], '1'); return 0
            end
            redis.call('SADD', KEYS[1], ARGV[1]); return 1
        """,
                2,
                f"admitted:{job_id}",
                f"url_limit:{job_id}",
                url_hash,
                str(max(1, min(limit, 30000))),
            )
        )

    async def dequeue(self, job_id: int) -> tuple[str, int] | None:
        raw = await self.redis.lpop(self._k_frontier(job_id))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        item = json.loads(raw)
        _, url_hash = normalize_url(item["url"])
        await self.redis.sadd(self._k_inflight(job_id), url_hash)
        return item["url"], int(item["depth"])

    async def ack(self, job_id: int, url_or_hash: str) -> None:
        if len(url_or_hash) == 40 and all(c in "0123456789abcdef" for c in url_or_hash):
            url_hash = url_or_hash
        else:
            _, url_hash = normalize_url(url_or_hash)
        await self.redis.srem(self._k_inflight(job_id), url_hash)

    async def size(self, job_id: int) -> int:
        return int(await self.redis.llen(self._k_frontier(job_id)))

    @staticmethod
    def _k_frontier(job_id: int) -> str:
        return f"frontier:{job_id}"

    @staticmethod
    def _k_seen(job_id: int) -> str:
        return f"seen:{job_id}"

    @staticmethod
    def _k_inflight(job_id: int) -> str:
        return f"inflight:{job_id}"
