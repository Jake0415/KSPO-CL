"""Session management — 호스트별 세션 풀 관리.

Scrapling의 FetcherSession 개념을 확장:
- 호스트별 쿠키/인증 상태 유지
- httpx + Playwright 세션 통합 관리
- 세션 만료/재생성 자동 처리
"""
from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "session_mgr")


@dataclass
class SessionEntry:
    host: str
    client: httpx.AsyncClient
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    request_count: int = 0
    max_requests: int = 1000
    max_age_seconds: float = 3600.0

    @property
    def is_expired(self) -> bool:
        age = time.time() - self.created_at
        return age > self.max_age_seconds or self.request_count >= self.max_requests

    def touch(self) -> None:
        self.last_used_at = time.time()
        self.request_count += 1


class SessionManager:
    """호스트별 httpx.AsyncClient 풀 — 커넥션 재사용 + 쿠키 유지.

    기존 Fetcher의 문제점(매 요청 새 client 생성)을 해결.
    """

    def __init__(
        self,
        *,
        max_connections: int = 20,
        max_keepalive: int = 10,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        max_requests_per_session: int = 1000,
        session_max_age: float = 3600.0,
    ) -> None:
        self._sessions: dict[str, SessionEntry] = {}
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=30.0,
            pool=10.0,
        )
        self._limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive,
        )
        self._max_requests = max_requests_per_session
        self._session_max_age = session_max_age

    async def get_client(
        self,
        host: str,
        *,
        user_agent: str | None = None,
        proxy: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.AsyncClient:
        """호스트별 AsyncClient 반환. 만료 시 자동 재생성."""
        entry = self._sessions.get(host)

        if entry is not None and not entry.is_expired:
            entry.touch()
            return entry.client

        # 기존 세션 정리
        if entry is not None:
            await self._close_entry(entry)

        # 새 세션 생성
        default_headers = {}
        if user_agent:
            default_headers["User-Agent"] = user_agent
        if headers:
            default_headers.update(headers)

        client = httpx.AsyncClient(
            http2=True,
            timeout=self._timeout,
            limits=self._limits,
            headers=default_headers or None,
            proxy=proxy,
            follow_redirects=True,
        )

        new_entry = SessionEntry(
            host=host,
            client=client,
            max_requests=self._max_requests,
            max_age_seconds=self._session_max_age,
        )
        self._sessions[host] = new_entry
        log.bind(event="session_created", host=host).debug("session created")
        return client

    async def _close_entry(self, entry: SessionEntry) -> None:
        with contextlib.suppress(Exception):
            await entry.client.aclose()
        log.bind(
            event="session_closed",
            host=entry.host,
            requests=entry.request_count,
        ).debug("session closed")

    async def close_all(self) -> None:
        """모든 세션 종료."""
        for entry in self._sessions.values():
            await self._close_entry(entry)
        self._sessions.clear()

    async def close_host(self, host: str) -> None:
        entry = self._sessions.pop(host, None)
        if entry:
            await self._close_entry(entry)

    async def cleanup_expired(self) -> int:
        """만료된 세션 정리. 반환: 정리된 수."""
        expired = [h for h, e in self._sessions.items() if e.is_expired]
        for host in expired:
            entry = self._sessions.pop(host)
            await self._close_entry(entry)
        return len(expired)

    @property
    def active_sessions(self) -> int:
        return len(self._sessions)

    def get_stats(self) -> list[dict[str, Any]]:
        return [
            {
                "host": e.host,
                "requests": e.request_count,
                "age_seconds": round(time.time() - e.created_at, 1),
                "expired": e.is_expired,
            }
            for e in self._sessions.values()
        ]
