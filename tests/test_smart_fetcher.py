"""Tests for crawl.smart_fetcher — SmartFetcher 자동 전략 선택."""

from __future__ import annotations

import pytest

from kspo_ingest.crawl.domain_profile import (
    CrawlStrategy,
    DomainProfile,
    DomainProfiler,
    HealthStatus,
)
from kspo_ingest.crawl.fetcher import FetchResult
from kspo_ingest.crawl.smart_fetcher import SmartFetcher


class TestSmartFetcherShouldEscalate:
    """_should_escalate 판단 로직 테스트."""

    def _make_result(self, body: bytes, status: int = 200, ct: str = "text/html") -> FetchResult:
        return FetchResult(
            url="https://example.com/",
            http_status=status,
            content_type=ct,
            raw_bytes=body,
            headers={},
            elapsed_ms=100,
        )

    def test_small_body_escalates(self):
        sf = SmartFetcher(auto_probe=False)
        result = self._make_result(b"<html><body></body></html>")
        assert sf._should_escalate(result) is True

    def test_large_ssr_renders_by_default(self):
        sf = SmartFetcher(auto_probe=False)
        body = b"<html><body><h1>Title</h1>" + b"<p>Content</p>" * 200 + b"</body></html>"
        result = self._make_result(body)
        assert sf._should_escalate(result) is True

    def test_static_opt_out(self):
        sf = SmartFetcher(auto_probe=False, render_all_html=False)
        body = b"<html><body>" + b"<p>Content</p>" * 200 + b"</body></html>"
        assert sf._should_escalate(self._make_result(body)) is False

    def test_dynamic_controls_override_opt_out(self):
        sf = SmartFetcher(auto_probe=False, render_all_html=False)
        body = b"<html><body><button>More</button>" + b"<p>Content</p>" * 200
        assert sf._should_escalate(self._make_result(body)) is True

    def test_error_status_no_escalate(self):
        sf = SmartFetcher(auto_probe=False)
        result = self._make_result(b"Not Found", status=404)
        assert sf._should_escalate(result) is False

    def test_non_html_no_escalate(self):
        sf = SmartFetcher(auto_probe=False)
        result = self._make_result(b'{"key":"value"}', ct="application/json")
        assert sf._should_escalate(result) is False

    def test_spa_shell_escalates(self):
        sf = SmartFetcher(auto_probe=False)
        body = (
            b'<html><body><div id="root"></div>'
            b'<script src="/bundle.abc123.js"></script></body></html>'
        )
        result = self._make_result(body)
        assert sf._should_escalate(result) is True

    def test_js_redirect_body_escalates(self):
        sf = SmartFetcher(auto_probe=False)
        body = b'<script>location.href="/main";</script>'
        result = self._make_result(body)
        assert sf._should_escalate(result) is True


class TestSmartFetcherStrategy:
    """프로파일 기반 전략 선택 테스트."""

    @pytest.mark.asyncio
    async def test_unreachable_raises(self):
        import time
        from unittest.mock import AsyncMock

        profiler = DomainProfiler()
        profiler._cache["dead.com"] = DomainProfile(
            host="dead.com",
            strategy=CrawlStrategy.UNREACHABLE,
            health=HealthStatus.DNS_FAIL,
            error="DNS fail",
            probed_at=time.time(),
        )
        browser = AsyncMock()
        browser.fetch.side_effect = ConnectionError("actual browser connection failed")
        sf = SmartFetcher(profiler=profiler, browser_fetcher=browser, auto_probe=False)
        with pytest.raises(ConnectionError, match="actual browser connection failed"):
            await sf.fetch("https://dead.com/", user_agent="test")
        browser.fetch.assert_awaited_once_with("https://dead.com/", user_agent="test")


@pytest.mark.asyncio
async def test_ssr_and_js_follow_both_render_arbitrary_sites():
    from unittest.mock import AsyncMock

    for strategy in (CrawlStrategy.HTTPX, CrawlStrategy.HTTPX_JS_FOLLOW):
        profiler = DomainProfiler()
        profiler._cache["museum.example"] = DomainProfile(
            host="museum.example",
            strategy=strategy,
            health=HealthStatus.HEALTHY,
        )
        http = AsyncMock()
        http.fetch.return_value = FetchResult(
            url="https://museum.example/about",
            http_status=200,
            content_type="text/html",
            raw_bytes=b"<p>Info</p>" * 200,
            headers={},
            elapsed_ms=1,
        )
        browser = AsyncMock()
        browser.fetch.return_value = http.fetch.return_value
        sf = SmartFetcher(
            http_fetcher=http, browser_fetcher=browser, profiler=profiler, auto_probe=False
        )
        await sf.fetch("https://museum.example/about", user_agent="test")
        browser.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_failure_records_incomplete_discovery():
    from unittest.mock import AsyncMock

    http = AsyncMock()
    http.fetch.return_value = FetchResult(
        url="https://other.example/",
        http_status=200,
        content_type="text/html",
        raw_bytes=b"<p>Info</p>" * 200,
        headers={},
        elapsed_ms=1,
    )
    browser = AsyncMock()
    browser.fetch.side_effect = RuntimeError("browser not installed")
    sf = SmartFetcher(http_fetcher=http, browser_fetcher=browser, auto_probe=False)
    result = await sf.fetch("https://other.example/", user_agent="test")
    assert result.discovery_report["needs_review"] is True


@pytest.mark.asyncio
async def test_failed_root_probe_retries_exact_input_and_caches_browser_success():
    import time
    from unittest.mock import AsyncMock

    profiler = DomainProfiler()
    profile = DomainProfile(
        host="example.com",
        strategy=CrawlStrategy.UNREACHABLE,
        health=HealthStatus.TIMEOUT,
        error="timeout",
        probed_at=time.time(),
    )
    profiler._cache[profile.host] = profile
    browser, http = AsyncMock(), AsyncMock()
    url = "https://example.com/sub/main.kspo?menu=17"
    browser.fetch.return_value = FetchResult(
        url=url,
        http_status=200,
        content_type="text/html",
        raw_bytes=b"public content",
        headers={},
        elapsed_ms=1,
    )
    sf = SmartFetcher(profiler=profiler, browser_fetcher=browser, http_fetcher=http)
    assert (await sf.fetch(url, user_agent="test")).url == url
    browser.fetch.assert_awaited_once_with(url, user_agent="test")
    http.fetch.assert_not_awaited()
    assert profile.strategy == CrawlStrategy.BROWSER
    assert profile.health == HealthStatus.HEALTHY and profile.error == ""
    assert profile.final_url == url
    await sf.fetch(url, user_agent="test")
    assert browser.fetch.await_count == 2
    sf.reset_failed_profile("example.com")
    assert profiler.get_cached("example.com") is profile


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,url", [(404, "https://example.com/missing"), (200, "https://other.com/main")]
)
async def test_failed_or_external_browser_response_does_not_promote_domain(status, url):
    import time
    from unittest.mock import AsyncMock

    profiler = DomainProfiler()
    profile = DomainProfile(
        host="example.com",
        strategy=CrawlStrategy.UNREACHABLE,
        health=HealthStatus.TIMEOUT,
        probed_at=time.time(),
    )
    profiler._cache[profile.host] = profile
    browser = AsyncMock()
    browser.fetch.return_value = FetchResult(
        url=url,
        http_status=status,
        content_type="text/html",
        raw_bytes=b"content",
        headers={},
        elapsed_ms=1,
    )
    sf = SmartFetcher(profiler=profiler, browser_fetcher=browser)
    result = await sf.fetch("https://example.com/main", user_agent="test")
    assert result.http_status == status
    assert profile.strategy == CrawlStrategy.UNREACHABLE


@pytest.mark.asyncio
async def test_failed_probe_browser_readiness_failure_propagates_without_http_fallback():
    import time
    from unittest.mock import AsyncMock

    from kspo_ingest.crawl.readiness import ContentReadinessError

    profiler = DomainProfiler()
    profiler._cache["example.com"] = DomainProfile(
        host="example.com", strategy=CrawlStrategy.UNREACHABLE, probed_at=time.time()
    )
    browser, http = AsyncMock(), AsyncMock()
    browser.fetch.side_effect = ContentReadinessError("body not ready")
    sf = SmartFetcher(profiler=profiler, browser_fetcher=browser, http_fetcher=http)
    with pytest.raises(ContentReadinessError, match="body not ready"):
        await sf.fetch("https://example.com/main", user_agent="test")
    browser.fetch.assert_awaited_once()
    http.fetch.assert_not_awaited()
