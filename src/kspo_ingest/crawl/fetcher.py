from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kspo_ingest.crawl.domain_profile import detect_js_redirect
from kspo_ingest.crawl.session_mgr import SessionManager


class ResponseTooLargeError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    http_status: int
    content_type: str
    raw_bytes: bytes
    headers: dict[str, str]
    elapsed_ms: int
    discovery_report: dict | None = None


class _RetryableHttpError(Exception):
    """5xx/429 — tenacity가 잡고 재시도."""


_RETRYABLE = (
    httpx.TransportError,
    httpx.TimeoutException,
    _RetryableHttpError,
)


class Fetcher:
    """httpx.AsyncClient(http2=True) wrapper — 커넥션 풀 재사용.

    개선사항 (vs v1):
    - SessionManager 기반 호스트별 커넥션 풀 재사용 (매 요청 client 생성 제거)
    - 프록시 지원 (per-request proxy override)
    - timeouts: connect 10s / read 30s
    - max_response_bytes: 응답 크기 상한 (기본 10MB)
    - tenacity: 5회 + 지수 백오프 (max 5분), 5xx/429/network만 재시도
    - 4xx (404 등)는 재시도 없이 그대로 반환
    """

    def __init__(
        self,
        max_response_bytes: int = 10 * 1024 * 1024,
        session_manager: SessionManager | None = None,
    ) -> None:
        self.max_response_bytes = max_response_bytes
        self._session_mgr = session_manager or SessionManager()
        self._owns_session_mgr = session_manager is None

    async def fetch(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None = None,
    ) -> FetchResult:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=300),
            retry=retry_if_exception_type(_RETRYABLE),
            reraise=True,
        ):
            with attempt:
                return await self._do_fetch(url, user_agent, proxy)
        raise RetryError(None)  # pragma: no cover — reraise=True

    async def _do_fetch(self, url: str, user_agent: str, proxy: str | None) -> FetchResult:
        started = time.perf_counter()
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        # same-origin Referer — Referer 헤더가 없으면 302로 랜딩 게이트로
        # 되돌리는 사이트(nfa.kspo.or.kr 등)에서 본문 페이지에 도달하기 위함.
        # 실제 브라우저가 사이트 내부 이동 시 보내는 헤더와 동일하다.
        referer = f"{parsed.scheme}://{host}/"
        client = await self._session_mgr.get_client(
            host,
            user_agent=user_agent,
            proxy=proxy,
        )

        try:
            resp = await client.get(url, follow_redirects=True, headers={"Referer": referer})
        except httpx.HTTPError:
            raise

        # Content-Length 사전 검사
        content_length = resp.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > self.max_response_bytes
        ):
            raise ResponseTooLargeError(
                f"content-length {content_length} > {self.max_response_bytes}"
            )

        body = resp.content
        if len(body) > self.max_response_bytes:
            raise ResponseTooLargeError(f"body {len(body)} > {self.max_response_bytes}")

        # 5xx / 429 → retry candidate
        if resp.status_code >= 500 or resp.status_code == 429:
            raise _RetryableHttpError(f"upstream {resp.status_code}")

        # JS redirect detection — small HTML with location.href
        if resp.status_code == 200 and len(body) < 1024:
            text = body.decode("utf-8", errors="replace")
            redirect_url = detect_js_redirect(text, str(resp.url))
            if redirect_url:
                resp = await client.get(
                    redirect_url, follow_redirects=True, headers={"Referer": referer}
                )
                body = resp.content
                if len(body) > self.max_response_bytes:
                    raise ResponseTooLargeError(f"body {len(body)} > {self.max_response_bytes}")

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return FetchResult(
            url=str(resp.url),
            http_status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            raw_bytes=body,
            headers={k.lower(): v for k, v in resp.headers.items()},
            elapsed_ms=elapsed_ms,
        )

    async def close(self) -> None:
        """세션 매니저 정리 — worker shutdown 시 호출."""
        if self._owns_session_mgr:
            await self._session_mgr.close_all()
