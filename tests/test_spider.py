"""Tests for crawl.spider — Async spider framework."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.crawl.fetcher import FetchResult
from kspo_ingest.crawl.spider import Spider, SpiderRequest, SpiderResponse, SpiderStats


class TestSpiderStats:
    def test_initial(self):
        stats = SpiderStats()
        assert stats.requests_sent == 0
        assert stats.responses_ok == 0
        assert stats.requests_per_second == 0.0

    def test_rps(self):
        stats = SpiderStats()
        stats.requests_sent = 100
        # elapsed_seconds > 0
        assert stats.requests_per_second >= 0


class TestSpiderRequest:
    def test_defaults(self):
        req = SpiderRequest(url="https://example.com")
        assert req.depth == 0
        assert req.callback == "parse"
        assert req.priority == 0


class TestSpiderResponse:
    def test_properties(self):
        result = FetchResult(
            url="https://example.com",
            http_status=200,
            content_type="text/html",
            raw_bytes=b"<html></html>",
            headers={},
            elapsed_ms=100,
        )
        req = SpiderRequest(url="https://example.com")
        resp = SpiderResponse(request=req, fetch_result=result, html="<html></html>")
        assert resp.url == "https://example.com"
        assert resp.status == 200


class TestSpider:
    def test_default_name(self):
        spider = Spider()
        assert spider.name == "base"

    def test_custom_spider(self):
        class MySpider(Spider):
            name = "test"
            start_urls = ["https://example.com"]

        spider = MySpider(concurrency=2, max_pages=10)
        assert spider.name == "test"
        assert spider.stats.requests_sent == 0

    def test_pause_resume(self):
        spider = Spider()
        spider.pause()
        assert spider._paused
        spider.resume()
        assert not spider._paused

    @pytest.mark.asyncio
    async def test_enqueue_dedup(self):
        spider = Spider()
        req1 = SpiderRequest(url="https://example.com")
        req2 = SpiderRequest(url="https://example.com")  # duplicate
        assert await spider._enqueue(req1) is True
        assert await spider._enqueue(req2) is False

    @pytest.mark.asyncio
    async def test_enqueue_max_pages(self):
        spider = Spider(max_pages=2)
        assert await spider._enqueue(SpiderRequest(url="https://a.com")) is True
        assert await spider._enqueue(SpiderRequest(url="https://b.com")) is True
        assert await spider._enqueue(SpiderRequest(url="https://c.com")) is False

    @pytest.mark.asyncio
    async def test_enqueue_max_depth(self):
        spider = Spider(max_depth=1)
        req = SpiderRequest(url="https://deep.com", depth=5)
        assert await spider._enqueue(req) is False
