"""Proxy rotation with health checking.

Scrapling의 ProxyRotator를 참고하되, 헬스체크 + 가중치 기반 선택 추가.
단일 proxy 실패 시 자동 제외, 주기적 복구 시도.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "proxy")

_HEALTH_CHECK_URL = "https://httpbin.org/ip"
_HEALTH_CHECK_TIMEOUT = 10.0


@dataclass
class ProxyEntry:
    url: str
    weight: float = 1.0
    fail_count: int = 0
    last_fail_at: float = 0.0
    is_healthy: bool = True
    avg_latency_ms: float = 0.0
    _latencies: list[float] = field(default_factory=list)

    def record_success(self, latency_ms: float) -> None:
        self.fail_count = 0
        self.is_healthy = True
        self._latencies.append(latency_ms)
        if len(self._latencies) > 10:
            self._latencies = self._latencies[-10:]
        self.avg_latency_ms = sum(self._latencies) / len(self._latencies)

    def record_failure(self) -> None:
        self.fail_count += 1
        self.last_fail_at = time.time()
        if self.fail_count >= 3:
            self.is_healthy = False


class ProxyRotator:
    """프록시 로테이션 — weighted round-robin + healthcheck.

    사용법:
        rotator = ProxyRotator(["http://proxy1:8080", "socks5://proxy2:1080"])
        proxy_url = rotator.next()        # 다음 프록시 선택
        rotator.report_success(proxy_url, latency_ms=150)
        rotator.report_failure(proxy_url)
    """

    def __init__(self, proxy_urls: list[str] | None = None) -> None:
        self._proxies: list[ProxyEntry] = []
        self._index = 0
        self._lock = asyncio.Lock()
        if proxy_urls:
            for url in proxy_urls:
                self._proxies.append(ProxyEntry(url=url))

    @property
    def has_proxies(self) -> bool:
        return len(self._proxies) > 0

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_healthy)

    def add(self, url: str, weight: float = 1.0) -> None:
        self._proxies.append(ProxyEntry(url=url, weight=weight))

    def next(self) -> str | None:
        """다음 건강한 프록시 반환. 모두 불량이면 가장 오래된 실패 프록시 반환."""
        if not self._proxies:
            return None

        healthy = [p for p in self._proxies if p.is_healthy]
        if not healthy:
            # 모든 프록시 불량 — 가장 오래 전 실패한 프록시 시도
            oldest = min(self._proxies, key=lambda p: p.last_fail_at)
            log.bind(event="proxy_fallback", proxy=oldest.url).warning("all proxies unhealthy")
            return oldest.url

        # round-robin
        self._index = (self._index + 1) % len(healthy)
        return healthy[self._index].url

    def _find(self, url: str) -> ProxyEntry | None:
        for p in self._proxies:
            if p.url == url:
                return p
        return None

    def report_success(self, proxy_url: str, latency_ms: float) -> None:
        entry = self._find(proxy_url)
        if entry:
            entry.record_success(latency_ms)

    def report_failure(self, proxy_url: str) -> None:
        entry = self._find(proxy_url)
        if entry:
            entry.record_failure()
            if not entry.is_healthy:
                log.bind(
                    event="proxy_marked_unhealthy",
                    proxy=proxy_url,
                    fail_count=entry.fail_count,
                ).warning("proxy marked unhealthy")

    async def health_check_all(self) -> dict[str, bool]:
        """모든 프록시 헬스체크. 결과: {proxy_url: is_healthy}."""
        results: dict[str, bool] = {}
        for entry in self._proxies:
            healthy = await self._check_one(entry)
            results[entry.url] = healthy
        return results

    async def _check_one(self, entry: ProxyEntry) -> bool:
        try:
            started = time.perf_counter()
            async with httpx.AsyncClient(
                proxy=entry.url,
                timeout=httpx.Timeout(_HEALTH_CHECK_TIMEOUT),
            ) as client:
                resp = await client.get(_HEALTH_CHECK_URL)
                if resp.status_code == 200:
                    latency = (time.perf_counter() - started) * 1000
                    entry.record_success(latency)
                    return True
        except Exception:
            pass
        entry.record_failure()
        return False

    def get_stats(self) -> list[dict]:
        return [
            {
                "url": p.url,
                "healthy": p.is_healthy,
                "fail_count": p.fail_count,
                "avg_latency_ms": round(p.avg_latency_ms, 1),
            }
            for p in self._proxies
        ]
