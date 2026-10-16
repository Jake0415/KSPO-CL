from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from robotexclusionrulesparser import RobotExclusionRulesParser

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "robots")


@dataclass
class _CacheEntry:
    parser: RobotExclusionRulesParser
    expires_at: float


class RobotsCache:
    """도메인별 robots.txt를 1시간 캐시.

    - is_allowed(url, user_agent) -> bool
    - fetch 실패 시 fail-open (허용) — 보수적 가정
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

    async def is_allowed(self, url: str, user_agent: str) -> bool:
        host_key = self._host_key(url)
        entry = self._cache.get(host_key)
        if entry is None or entry.expires_at < time.time():
            entry = await self._refresh(host_key, url)
            self._cache[host_key] = entry

        return entry.parser.is_allowed(user_agent, url)

    def _host_key(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def _refresh(self, host_key: str, url: str) -> _CacheEntry:
        parts = urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        parser = RobotExclusionRulesParser()

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                resp = await client.get(robots_url)
            if resp.status_code == 200:
                parser.parse(resp.text)
                log.bind(event="robots_loaded", host=parts.netloc, status=200).info("robots loaded")
            else:
                # 4xx/5xx — fail-open (parser는 빈 상태 → allow all)
                log.bind(
                    event="robots_unavailable", host=parts.netloc, status=resp.status_code
                ).warning(
                    "robots.txt non-200 — fail-open"
                )
        except Exception as e:
            log.bind(event="robots_fetch_failed", host=parts.netloc, error=str(e)).warning(
                "robots.txt fetch failed — fail-open"
            )

        return _CacheEntry(parser=parser, expires_at=time.time() + self._ttl)
