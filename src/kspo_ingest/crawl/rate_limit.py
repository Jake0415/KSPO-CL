from __future__ import annotations

import asyncio
import time

from redis.asyncio import Redis


class HostRateLimit:
    """Host-bucket 단순 token bucket — 단일 worker 가정.

    Redis ZSET `host_bucket:{host}` 에 'available_at_ts' 스코어 1개만 유지.
    동시 worker 도입 시 Lua atomic으로 강화 (Tier 2).
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def acquire(self, host: str, rps: float) -> None:
        if rps <= 0:
            return
        interval = 1.0 / rps
        key = f"host_bucket:{host}"
        now = time.time()

        # 가장 최근 available_at 조회
        latest = await self.redis.zrange(key, -1, -1, withscores=True)
        available_at = float(latest[0][1]) if latest else 0.0

        if available_at <= now:
            # 즉시 통과 — 다음 요청은 now+interval 이후 허용
            next_at = now + interval
            await self.redis.zadd(key, {str(next_at): next_at})
        else:
            wait = available_at - now
            await asyncio.sleep(wait)
            next_at = available_at + interval
            await self.redis.zadd(key, {str(next_at): next_at})

        # 오래된 entry trim (최근 1개만 유지)
        await self.redis.zremrangebyrank(key, 0, -2)
        await self.redis.expire(key, 60)
