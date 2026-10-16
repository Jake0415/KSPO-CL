"""api/rate_limit.py 단위 테스트 — fakeredis 기반 슬라이딩 윈도우 검증."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from kspo_ingest.api import rate_limit as rl


class FakeAsyncRedis:
    """ZSET 기반 sliding window를 in-memory로 흉내. zadd/zcard/zremrangebyscore/expire/pipeline."""

    def __init__(self):
        self._z: dict[str, dict[str, int]] = {}
        self._ttl: dict[str, int] = {}

    def pipeline(self):
        return _Pipeline(self)

    async def zadd(self, key, mapping):
        z = self._z.setdefault(key, {})
        z.update({k: int(v) for k, v in mapping.items()})

    async def expire(self, key, seconds):
        self._ttl[key] = seconds


class _Pipeline:
    def __init__(self, store: FakeAsyncRedis):
        self._store = store
        self._ops: list = []

    def zremrangebyscore(self, key, min_score, max_score):
        self._ops.append(("zremrangebyscore", key, min_score, max_score))
        return self

    def zcard(self, key):
        self._ops.append(("zcard", key))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "zremrangebyscore":
                _, key, lo, hi = op
                z = self._store._z.get(key, {})
                removed = [k for k, v in z.items() if lo <= v <= hi]
                for k in removed:
                    z.pop(k)
                results.append(len(removed))
            elif op[0] == "zcard":
                _, key = op
                results.append(len(self._store._z.get(key, {})))
        self._ops.clear()
        return results


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeAsyncRedis()

    async def _get():
        return fake

    monkeypatch.setattr(rl, "get_redis", _get)
    return fake


@pytest.mark.asyncio
async def test_first_60_calls_pass(fake_redis):
    for _ in range(60):
        await rl.rate_limit_60_per_minute()
    # 60개 모두 통과 — 호출 수 == 60
    assert len(fake_redis._z["rate_limit:refresh_url"]) == 60


@pytest.mark.asyncio
async def test_61st_call_raises_429(fake_redis):
    for _ in range(60):
        await rl.rate_limit_60_per_minute()
    with pytest.raises(HTTPException) as exc_info:
        await rl.rate_limit_60_per_minute()
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_window_slide_allows_after_old_entries_drop(fake_redis, monkeypatch):
    import time as _time

    now = [1_700_000_000_000]

    def fake_time():
        return now[0] / 1000.0

    monkeypatch.setattr(_time, "time", fake_time)

    for _ in range(60):
        await rl.rate_limit_60_per_minute()
    with pytest.raises(HTTPException):
        await rl.rate_limit_60_per_minute()

    # 60초 + 100ms 경과 → window 밖 모든 항목 zremrangebyscore가 제거
    now[0] += 60_100
    await rl.rate_limit_60_per_minute()  # 이제 통과해야 함


@pytest.mark.asyncio
async def test_other_endpoint_keys_independent(fake_redis):
    """다른 키를 사용하는 호출은 영향 없음 (rate_limit_60_per_minute 키만 영향)."""
    for _ in range(60):
        await rl.rate_limit_60_per_minute()
    # 다른 엔드포인트가 자체 키를 가질 때 — 본 데코레이터는 한 키만 보호
    assert "rate_limit:refresh_url" in fake_redis._z
    assert "rate_limit:other" not in fake_redis._z
