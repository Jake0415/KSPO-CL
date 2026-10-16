"""Async Spider framework — Scrapy 스타일 API + asyncio 동시성.

Scrapling의 Spider를 참고하되, 기존 KSPO 파이프라인과 통합:
- start_urls + parse() 콜백 패턴
- asyncio.Semaphore 기반 동시성 제어
- 도메인별 rate limiting 연동
- 체크포인트 기반 pause/resume
- 결과 스트리밍 (async generator)

기존 enqueue_seeds의 순차 BFS를 concurrent BFS로 대체 가능.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from kspo_ingest.crawl.fetcher import Fetcher, FetchResult
from kspo_ingest.crawl.rate_limit import HostRateLimit
from kspo_ingest.crawl.smart_fetcher import SmartFetcher
from kspo_ingest.crawl.url_class import is_non_content_url
from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "spider")


@dataclass
class SpiderRequest:
    """크롤 요청 — URL + 메타데이터."""

    url: str
    depth: int = 0
    callback: str = "parse"
    meta: dict[str, Any] = field(default_factory=dict)
    priority: int = 0  # 높을수록 먼저


@dataclass
class SpiderResponse:
    """크롤 응답 — FetchResult + 메타데이터."""

    request: SpiderRequest
    fetch_result: FetchResult
    html: str

    @property
    def url(self) -> str:
        return self.fetch_result.url

    @property
    def status(self) -> int:
        return self.fetch_result.http_status


@dataclass
class SpiderStats:
    """크롤 통계."""

    started_at: float = field(default_factory=time.time)
    requests_sent: int = 0
    responses_ok: int = 0
    responses_error: int = 0
    items_yielded: int = 0
    bytes_downloaded: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at

    @property
    def requests_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0.0
        return self.requests_sent / elapsed


class Spider:
    """비동기 스파이더 — Scrapy 스타일 API.

    사용법:
        class MySpider(Spider):
            name = "example"
            start_urls = ["https://example.com/"]

            async def parse(self, response: SpiderResponse):
                for item in self.select(response.html, "div.product"):
                    yield {"title": item.text()}

        spider = MySpider(concurrency=8)
        async for item in spider.crawl():
            print(item)
    """

    name: str = "base"
    start_urls: list[str] = []

    def __init__(
        self,
        *,
        concurrency: int = 8,
        max_depth: int = 10,
        max_pages: int = 20000,
        rate_limit_rps: float = 1.5,
        user_agent: str = "kspo-ingest/0.2",
        fetcher: Fetcher | SmartFetcher | None = None,
        rate_limiter: HostRateLimit | None = None,
    ) -> None:
        self._concurrency = concurrency
        self._max_depth = max_depth
        self._max_pages = max_pages
        self._rate_limit_rps = rate_limit_rps
        self._user_agent = user_agent
        self._fetcher = fetcher or SmartFetcher()
        self._rate_limiter = rate_limiter
        self._stats = SpiderStats()
        self._seen: set[str] = set()
        self._queue: asyncio.PriorityQueue[tuple[int, int, SpiderRequest]] = asyncio.PriorityQueue()
        self._paused = False
        self._enqueue_counter = 0
        self._items: asyncio.Queue[Any] = asyncio.Queue()
        self._done = False
        self._semaphore = asyncio.Semaphore(concurrency)

    @property
    def stats(self) -> SpiderStats:
        return self._stats

    def pause(self) -> None:
        self._paused = True
        log.bind(event="spider_paused", name=self.name).info("spider paused")

    def resume(self) -> None:
        self._paused = False
        log.bind(event="spider_resumed", name=self.name).info("spider resumed")

    async def parse(self, response: SpiderResponse) -> AsyncIterator[Any]:
        """기본 parse 콜백 — 서브클래스에서 오버라이드."""
        yield {"url": response.url, "status": response.status}

    async def crawl(self) -> AsyncIterator[Any]:
        """크롤 실행 — 결과를 async generator로 스트리밍."""
        # seed URLs 투입
        for url in self.start_urls:
            await self._enqueue(SpiderRequest(url=url, depth=0))

        # worker 시작
        workers = [asyncio.create_task(self._worker(i)) for i in range(self._concurrency)]

        # consumer: items queue에서 결과 수집
        try:
            while not self._done or not self._items.empty():
                try:
                    item = await asyncio.wait_for(self._items.get(), timeout=1.0)
                    yield item
                except TimeoutError:
                    # queue 비어있고 모든 worker가 idle이면 종료
                    if self._queue.empty() and all(w.done() for w in workers):
                        break
                    continue
        finally:
            self._done = True
            for w in workers:
                w.cancel()

        log.bind(
            event="spider_done",
            name=self.name,
            requests=self._stats.requests_sent,
            items=self._stats.items_yielded,
            elapsed=round(self._stats.elapsed_seconds, 1),
        ).info("spider done")

    async def _enqueue(self, request: SpiderRequest) -> bool:
        if request.url in self._seen:
            return False
        if len(self._seen) >= self._max_pages:
            return False
        if request.depth > self._max_depth:
            return False
        # 엔진 공통 규칙: 로그인/회원/인증/유틸 페이지는 frontier 진입 금지.
        if is_non_content_url(request.url):
            return False
        self._seen.add(request.url)
        # negative priority for PriorityQueue (higher priority = lower number)
        # counter breaks ties between same-priority items
        self._enqueue_counter += 1
        await self._queue.put((-request.priority, self._enqueue_counter, request))
        return True

    async def _worker(self, worker_id: int) -> None:
        while not self._done:
            if self._paused:
                await asyncio.sleep(0.5)
                continue

            try:
                _, _, request = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except TimeoutError:
                if self._queue.empty():
                    break
                continue

            async with self._semaphore:
                await self._process_request(request)

    async def _process_request(self, request: SpiderRequest) -> None:
        host = urlparse(request.url).netloc.lower()

        # rate limiting
        if self._rate_limiter:
            await self._rate_limiter.acquire(host, self._rate_limit_rps)

        self._stats.requests_sent += 1

        try:
            result = await self._fetcher.fetch(
                request.url,
                user_agent=self._user_agent,
            )
        except Exception as e:
            self._stats.responses_error += 1
            log.bind(
                event="spider_fetch_error",
                url=request.url,
                error=str(e),
            ).warning("fetch error")
            return

        if result.http_status >= 400:
            self._stats.responses_error += 1
            return

        self._stats.responses_ok += 1
        self._stats.bytes_downloaded += len(result.raw_bytes)

        html = result.raw_bytes.decode("utf-8", errors="replace")
        response = SpiderResponse(
            request=request,
            fetch_result=result,
            html=html,
        )

        # parse 콜백 실행
        callback_name = request.callback
        callback = getattr(self, callback_name, self.parse)
        async for item in callback(response):
            if isinstance(item, SpiderRequest):
                # 새 URL 발견 → enqueue
                if item.depth == 0:
                    item.depth = request.depth + 1
                await self._enqueue(item)
            else:
                self._stats.items_yielded += 1
                await self._items.put(item)

    async def close(self) -> None:
        """리소스 정리."""
        self._done = True
        await self._fetcher.close()
