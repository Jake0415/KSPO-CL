"""API rate limit — Redis 슬라이딩 윈도우 기반 FastAPI 의존성.

전역 단일 Admin 가정이므로 도메인 단위가 아닌 endpoint 단위 키. ZSET에 unix_ms를 score
로 저장하여 윈도우 밖 항목 제거 + 현재 카운트 조회 + 추가를 pipeline으로 원자 수행.
"""
from __future__ import annotations

import time
import uuid

from fastapi import HTTPException, status
from redis.asyncio import Redis

from kspo_ingest.settings import settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def _check_and_record(*, key: str, limit: int, window_seconds: int) -> None:
    redis = await get_redis()
    now_ms = int(time.time() * 1000)
    window_ms = window_seconds * 1000

    pipe = redis.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    pipe.zcard(key)
    _, count = await pipe.execute()
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(window_seconds)},
        )
    await redis.zadd(key, {uuid.uuid4().hex: now_ms})
    await redis.expire(key, window_seconds + 5)


async def rate_limit_60_per_minute() -> None:
    """`/api/jobs/refresh-url`용 — 분당 60회. 다른 엔드포인트는 영향 없음."""
    await _check_and_record(
        key="rate_limit:refresh_url", limit=60, window_seconds=60
    )
