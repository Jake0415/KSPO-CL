"""Tests for crawl.domain_profile — DomainProfile + AutoStrategy."""

from __future__ import annotations

import pytest

from kspo_ingest.crawl.domain_profile import (
    CrawlStrategy,
    DomainProfile,
    HealthStatus,
    count_internal_links,
    detect_canonical,
    detect_js_redirect,
    detect_meta_refresh,
    detect_spa,
)


class TestDetectJsRedirect:
    def test_location_href(self):
        body = '<script>location.href = "/main";</script>'
        assert detect_js_redirect(body, "https://example.com/") == "https://example.com/main"

    def test_window_location(self):
        body = "<script>window.location = '/page';</script>"
        assert detect_js_redirect(body, "https://example.com/") == "https://example.com/page"

    def test_location_replace(self):
        body = "<script>location.replace('/new');</script>"
        assert detect_js_redirect(body, "https://example.com/") == "https://example.com/new"

    def test_window_location_replace(self):
        body = "<script>window.location.replace('/new');</script>"
        assert detect_js_redirect(body, "https://example.com/") == "https://example.com/new"

    def test_document_location(self):
        body = '<script>document.location = "/page";</script>'
        assert detect_js_redirect(body, "https://example.com/") == "https://example.com/page"

    def test_no_redirect(self):
        body = "<html><body>Hello</body></html>"
        assert detect_js_redirect(body, "https://example.com/") is None

    def test_absolute_url(self):
        body = '<script>location.href = "https://other.com/page";</script>'
        assert detect_js_redirect(body, "https://example.com/") == "https://other.com/page"

    def test_kcycle_pattern(self):
        """실제 kcycle.or.kr 패턴."""
        body = '<script type="text/javaScript">\n    location.href = "/main";\n</script> '
        assert (
            detect_js_redirect(body, "https://www.kcycle.or.kr/") == "https://www.kcycle.or.kr/main"
        )

    def test_parktel_pattern(self):
        """실제 parktel.co.kr 패턴."""
        body = '<script>\n\tlocation.href="/main/main.do";\n</script>'
        assert (
            detect_js_redirect(body, "https://www.parktel.co.kr/")
            == "https://www.parktel.co.kr/main/main.do"
        )

    def test_nfa_pattern(self):
        """실제 nfa.kspo.or.kr 패턴."""
        body = '<script type="text/javascript">\n\tlocation.href="/beforeReserve.kspo";\n</script>'
        assert (
            detect_js_redirect(body, "https://nfa.kspo.or.kr/")
            == "https://nfa.kspo.or.kr/beforeReserve.kspo"
        )


class TestDetectMetaRefresh:
    def test_basic(self):
        body = '<meta http-equiv="refresh" content="0;url=/new">'
        assert detect_meta_refresh(body, "https://example.com/") == "https://example.com/new"

    def test_with_delay(self):
        body = '<meta http-equiv="refresh" content="5; url=https://other.com/">'
        assert detect_meta_refresh(body, "https://example.com/") == "https://other.com/"

    def test_no_refresh(self):
        body = "<html><head></head></html>"
        assert detect_meta_refresh(body, "https://example.com/") is None


class TestDetectCanonical:
    def test_basic(self):
        body = '<link rel="canonical" href="https://example.com/page">'
        assert detect_canonical(body) == "https://example.com/page"

    def test_no_canonical(self):
        body = "<html><head></head></html>"
        assert detect_canonical(body) is None


class TestDetectSpa:
    def test_react_app(self):
        body = (
            '<html><body><div id="root"></div>'
            '<script src="/static/js/main.abc123.js"></script></body></html>'
        )
        assert detect_spa(body) is True

    def test_next_app(self):
        body = (
            '<html><body><div id="__next"></div>'
            '<script src="/chunks/main.def456.js"></script></body></html>'
        )
        assert detect_spa(body) is True

    def test_large_ssr_page(self):
        body = "<html><body>" + "x" * 60000 + "</body></html>"
        assert detect_spa(body) is False

    def test_normal_html(self):
        body = "<html><body><h1>Hello</h1><p>" + "Content " * 100 + "</p></body></html>"
        assert detect_spa(body) is False


class TestCountInternalLinks:
    def test_counts(self):
        body = """
        <html><body>
            <a href="/page1">Page 1</a>
            <a href="/page2">Page 2</a>
            <a href="https://external.com">External</a>
            <a href="javascript:void(0)">JS</a>
            <a href="#">Anchor</a>
        </body></html>"""
        assert count_internal_links(body, "example.com") == 2

    def test_absolute_internal(self):
        body = '<a href="https://example.com/about">About</a>'
        assert count_internal_links(body, "example.com") == 1


class TestDomainProfile:
    def test_defaults(self):
        p = DomainProfile(host="example.com")
        assert p.strategy == CrawlStrategy.HTTPX
        assert p.health == HealthStatus.UNKNOWN
        assert not p.js_redirect
        assert not p.is_spa


class TestFailedProfileExpiry:
    def test_only_failed_profiles_expire_and_can_be_reset(self):
        from unittest.mock import patch

        from kspo_ingest.crawl.domain_profile import DomainProfiler

        profiler = DomainProfiler(failure_ttl_seconds=60)
        failed = DomainProfile(host="failed.kr", strategy=CrawlStrategy.UNREACHABLE, probed_at=100)
        healthy = DomainProfile(host="healthy.kr", probed_at=1)
        profiler._cache.update({failed.host: failed, healthy.host: healthy})
        with patch("kspo_ingest.crawl.domain_profile.time.time", return_value=159):
            assert profiler.get_cached(failed.host) is failed
        with patch("kspo_ingest.crawl.domain_profile.time.time", return_value=160):
            assert profiler.get_cached(failed.host) is None
            assert profiler.get_all_cached() == {healthy.host: healthy}
        profiler._cache[failed.host] = failed
        profiler.invalidate_failed(failed.host)
        profiler.invalidate_failed(healthy.host)
        assert failed.host not in profiler._cache
        assert profiler.get_cached(healthy.host) is healthy

    @pytest.mark.asyncio
    async def test_probe_rechecks_expired_failure(self):
        from unittest.mock import AsyncMock, patch

        import httpx

        from kspo_ingest.crawl.domain_profile import DomainProfiler

        profiler = DomainProfiler(failure_ttl_seconds=60)
        profiler._cache["example.com"] = DomainProfile(
            host="example.com", strategy=CrawlStrategy.UNREACHABLE, probed_at=1
        )
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = httpx.Response(
            200,
            text="<body>Public content</body>",
            request=httpx.Request("GET", "https://example.com/"),
        )
        with (
            patch("kspo_ingest.crawl.domain_profile.httpx.AsyncClient", return_value=client),
            patch.object(profiler, "_check_robots_sitemap", new=AsyncMock()),
        ):
            result = await profiler.probe("example.com")
        assert result.strategy != CrawlStrategy.UNREACHABLE
        assert result.health == HealthStatus.HEALTHY
        client.get.assert_awaited_once()
