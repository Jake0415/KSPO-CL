"""Tests for crawl.browser — BrowserFetcher with mocked Playwright."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kspo_ingest.crawl.browser import (
    DEFAULT_HOST_CONFIGS,
    BrowserFetcher,
    HostBrowserConfig,
    _HostSession,
)
from kspo_ingest.crawl.fetcher import FetchResult
from kspo_ingest.crawl.stealth import get_profile


@pytest.fixture(autouse=True)
def isolate_readiness():
    # Readiness state transitions and real DOM are tested in test_readiness.
    with (
        patch("kspo_ingest.crawl.browser.ContentWaiter") as waiter,
        patch("kspo_ingest.crawl.browser.wait_initial_content", new=AsyncMock()),
    ):
        waiter.return_value.wait = AsyncMock(return_value={"ready": True})
        yield waiter


@pytest.fixture(autouse=True)
def isolate_dynamic_expansion():
    # Browser routing tests isolate the separately tested dynamic exploration layer.
    async def expand(page, **kwargs):
        return await page.content(), {}

    with patch("kspo_ingest.crawl.browser.expand_readonly", side_effect=expand):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(url: str = "https://example.com/page", content: str = "<html></html>") -> MagicMock:
    """Build a mock Playwright Page."""
    page = MagicMock()
    page.url = url
    page.goto = AsyncMock(return_value=_make_response())
    page.content = AsyncMock(return_value=content)
    page.title = AsyncMock(return_value="Test Page")
    page.close = AsyncMock()
    page.add_init_script = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)
    page.evaluate = AsyncMock(return_value=[])
    page.expect_navigation = MagicMock()
    return page


def _make_response(status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.headers_array = AsyncMock(return_value=[{"name": "Content-Type", "value": "text/html"}])
    return resp


def _make_context(page: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.new_page = AsyncMock(return_value=page)
    ctx.close = AsyncMock()
    return ctx


def _make_browser(ctx: MagicMock) -> MagicMock:
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=ctx)
    browser.close = AsyncMock()
    return browser


def _make_playwright(browser: MagicMock) -> MagicMock:
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()
    return pw


# ---------------------------------------------------------------------------
# 1. HostBrowserConfig defaults
# ---------------------------------------------------------------------------


class TestHostBrowserConfig:
    def test_defaults(self):
        cfg = HostBrowserConfig()
        assert cfg.warmup_url is None
        assert cfg.click_selector is None
        assert cfg.needs_js_nav is False
        assert cfg.wait_until == "domcontentloaded"
        assert cfg.timeout_ms == 30000
        assert cfg.stealth_profile is None

    def test_custom_values(self):
        cfg = HostBrowserConfig(
            warmup_url="https://example.com",
            click_selector="a.nav",
            needs_js_nav=True,
            wait_until="load",
            timeout_ms=10000,
            stealth_profile="chrome_win",
        )
        assert cfg.warmup_url == "https://example.com"
        assert cfg.click_selector == "a.nav"
        assert cfg.needs_js_nav is True
        assert cfg.wait_until == "load"
        assert cfg.timeout_ms == 10000
        assert cfg.stealth_profile == "chrome_win"


# ---------------------------------------------------------------------------
# 2. DEFAULT_HOST_CONFIGS
# ---------------------------------------------------------------------------


class TestDefaultHostConfigs:
    def test_nfa_entry_exists(self):
        assert "nfa.kspo.or.kr" in DEFAULT_HOST_CONFIGS

    def test_nfa_warmup_url(self):
        cfg = DEFAULT_HOST_CONFIGS["nfa.kspo.or.kr"]
        assert cfg.warmup_url is None

    def test_nfa_click_selector(self):
        cfg = DEFAULT_HOST_CONFIGS["nfa.kspo.or.kr"]
        assert cfg.click_selector == 'a[href="/main.kspo"]'

    def test_nfa_needs_js_nav(self):
        cfg = DEFAULT_HOST_CONFIGS["nfa.kspo.or.kr"]
        assert cfg.needs_js_nav is False


# ---------------------------------------------------------------------------
# 3. BrowserFetcher.__init__
# ---------------------------------------------------------------------------


class TestBrowserFetcherInit:
    def test_default_values(self):
        fetcher = BrowserFetcher()
        assert fetcher._proxy is None
        assert fetcher._headless is True
        assert fetcher._default_profile_name is None
        assert fetcher._browser is None
        assert fetcher._pw is None
        assert fetcher._sessions == {}

    def test_default_host_configs_merged(self):
        fetcher = BrowserFetcher()
        assert "nfa.kspo.or.kr" in fetcher._host_configs

    def test_custom_host_configs_override(self):
        custom = HostBrowserConfig(wait_until="load")
        fetcher = BrowserFetcher(host_configs={"custom.host": custom})
        assert "custom.host" in fetcher._host_configs
        assert "nfa.kspo.or.kr" in fetcher._host_configs  # defaults still present

    def test_proxy_and_headless(self):
        fetcher = BrowserFetcher(proxy="http://proxy:8080", headless=False)
        assert fetcher._proxy == "http://proxy:8080"
        assert fetcher._headless is False

    def test_default_profile_name(self):
        fetcher = BrowserFetcher(default_profile="chrome_win")
        assert fetcher._default_profile_name == "chrome_win"


# ---------------------------------------------------------------------------
# 4 & 5. BrowserFetcher.fetch() — goto vs js_nav routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBrowserFetcherFetch:
    async def _make_fetcher_with_session(self, host: str, config: HostBrowserConfig):
        """Build a BrowserFetcher with a pre-populated session (bypasses _ensure_browser)."""
        fetcher = BrowserFetcher()
        page = _make_page(url=f"https://{host}/page")
        ctx = _make_context(page)
        profile = get_profile("chrome_win")
        session = _HostSession(ctx=ctx, page=page, config=config, profile=profile)
        fetcher._sessions[host] = session
        return fetcher, session, page

    async def test_fetch_delegates_to_fetch_goto_for_normal_host(self):
        host = "example.com"
        config = HostBrowserConfig(needs_js_nav=False)
        fetcher, session, page = await self._make_fetcher_with_session(host, config)

        new_page = _make_page(url=f"https://{host}/page", content="<html>hello</html>")
        session.ctx.new_page = AsyncMock(return_value=new_page)

        result = await fetcher.fetch(f"https://{host}/page")

        assert isinstance(result, FetchResult)
        new_page.goto.assert_awaited_once()
        assert result.http_status == 200
        assert result.raw_bytes == b"<html>hello</html>"

    async def test_fetch_delegates_to_fetch_js_nav_for_js_nav_host(self):
        host = "nfa.kspo.or.kr"
        config = HostBrowserConfig(needs_js_nav=True)
        fetcher, session, page = await self._make_fetcher_with_session(host, config)

        # page.expect_navigation must return an async context manager
        nav_cm = MagicMock()
        nav_cm.__aenter__ = AsyncMock(return_value=None)
        nav_cm.__aexit__ = AsyncMock(return_value=False)
        page.expect_navigation = MagicMock(return_value=nav_cm)
        page.content = AsyncMock(return_value="<html>js nav</html>")

        result = await fetcher.fetch(f"https://{host}/some/path")

        assert isinstance(result, FetchResult)
        assert result.http_status == 200
        assert result.content_type == "text/html"
        assert b"js nav" in result.raw_bytes

    async def test_fetch_js_nav_fallback_on_navigation_error(self):
        """If expect_navigation raises, wait_for_timeout is called and content still returned."""
        host = "nfa.kspo.or.kr"
        config = HostBrowserConfig(needs_js_nav=True)
        fetcher, session, page = await self._make_fetcher_with_session(host, config)

        nav_cm = MagicMock()
        nav_cm.__aenter__ = AsyncMock(side_effect=Exception("nav timeout"))
        nav_cm.__aexit__ = AsyncMock(return_value=False)
        page.expect_navigation = MagicMock(return_value=nav_cm)
        page.content = AsyncMock(return_value="<html>fallback</html>")

        result = await fetcher.fetch(f"https://{host}/path")

        page.wait_for_timeout.assert_awaited_once_with(2000)
        assert b"fallback" in result.raw_bytes


# ---------------------------------------------------------------------------
# 6. BrowserFetcher.close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBrowserFetcherClose:
    async def test_close_clears_sessions_and_stops_browser(self):
        fetcher = BrowserFetcher()

        page1 = _make_page()
        ctx1 = _make_context(page1)
        profile = get_profile("chrome_win")
        fetcher._sessions["host1.com"] = _HostSession(
            ctx=ctx1, page=page1, config=HostBrowserConfig(), profile=profile
        )

        mock_browser = MagicMock()
        mock_browser.close = AsyncMock()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock()
        fetcher._browser = mock_browser
        fetcher._pw = mock_pw

        await fetcher.close()

        page1.close.assert_awaited_once()
        ctx1.close.assert_awaited_once()
        assert fetcher._sessions == {}
        mock_browser.close.assert_awaited_once()
        mock_pw.stop.assert_awaited_once()

    async def test_close_with_no_browser_does_not_raise(self):
        fetcher = BrowserFetcher()
        # _browser and _pw are None — should not raise
        await fetcher.close()

    async def test_close_tolerates_session_close_error(self):
        fetcher = BrowserFetcher()

        page = _make_page()
        page.close = AsyncMock(side_effect=Exception("already closed"))
        ctx = _make_context(page)
        profile = get_profile("chrome_win")
        fetcher._sessions["bad.host"] = _HostSession(
            ctx=ctx, page=page, config=HostBrowserConfig(), profile=profile
        )

        mock_browser = MagicMock()
        mock_browser.close = AsyncMock()
        mock_pw = MagicMock()
        mock_pw.stop = AsyncMock()
        fetcher._browser = mock_browser
        fetcher._pw = mock_pw

        # Should not raise despite session.page.close() failing
        await fetcher.close()
        assert fetcher._sessions == {}


# ---------------------------------------------------------------------------
# 7. get_dom_snapshot()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetDomSnapshot:
    async def test_returns_correct_structure(self):
        fetcher = BrowserFetcher()

        interactive = [{"tag": "a", "text": "Link", "href": "/foo", "index": 0}]
        snap_page = _make_page(url="https://example.com/page", content="<html>snap</html>")
        snap_page.title = AsyncMock(return_value="Snap Title")
        snap_page.evaluate = AsyncMock(return_value=interactive)

        ctx = _make_context(snap_page)
        profile = get_profile("chrome_win")
        fetcher._sessions["example.com"] = _HostSession(
            ctx=ctx, page=snap_page, config=HostBrowserConfig(), profile=profile
        )

        result = await fetcher.get_dom_snapshot("https://example.com/page")

        assert "html" in result
        assert "title" in result
        assert "url" in result
        assert "interactive_elements" in result
        assert result["title"] == "Snap Title"
        assert result["html"] == "<html>snap</html>"
        assert result["interactive_elements"] == interactive
        snap_page.close.assert_awaited_once()

    async def test_dom_snapshot_closes_page_on_error(self):
        fetcher = BrowserFetcher()

        snap_page = _make_page()
        snap_page.goto = AsyncMock(side_effect=Exception("goto failed"))
        snap_page.close = AsyncMock()

        ctx = _make_context(snap_page)
        profile = get_profile("chrome_win")
        fetcher._sessions["example.com"] = _HostSession(
            ctx=ctx, page=snap_page, config=HostBrowserConfig(), profile=profile
        )

        with pytest.raises(Exception, match="goto failed"):
            await fetcher.get_dom_snapshot("https://example.com/page")

        snap_page.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# 8. register_host_config
# ---------------------------------------------------------------------------


class TestRegisterHostConfig:
    def test_register_adds_config(self):
        fetcher = BrowserFetcher()
        cfg = HostBrowserConfig(wait_until="load")
        fetcher.register_host_config("new.host", cfg)
        assert fetcher._host_configs["new.host"] is cfg


@pytest.mark.asyncio
async def test_navigation_timeout_recovers_only_readable_requested_document():
    from playwright.async_api import TimeoutError as BrowserTimeoutError

    page = _make_page()
    page.goto.side_effect = BrowserTimeoutError("navigation deadline")
    page.wait_for_function = AsyncMock()
    fetcher = BrowserFetcher()
    assert await fetcher._goto_ready(page, page.url, HostBrowserConfig()) is None

    page.url = "about:blank"
    with pytest.raises(BrowserTimeoutError):
        await fetcher._goto_ready(page, "https://example.com/page", HostBrowserConfig())


@pytest.mark.asyncio
async def test_empty_or_unready_page_still_fails(isolate_readiness):
    from playwright.async_api import TimeoutError as BrowserTimeoutError

    page = _make_page()
    page.goto.side_effect = BrowserTimeoutError("navigation deadline")
    isolate_readiness.return_value.wait.side_effect = BrowserTimeoutError("empty DOM")
    with pytest.raises(BrowserTimeoutError):
        await BrowserFetcher()._goto_ready(page, page.url, HostBrowserConfig())


@pytest.mark.asyncio
async def test_navigation_default_does_not_wait_for_network_idle():
    page = _make_page()
    await BrowserFetcher()._goto_ready(page, page.url, HostBrowserConfig())
    assert page.goto.call_args.kwargs["wait_until"] == "domcontentloaded"
    page.wait_for_load_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigation_passes_configured_referer():
    from kspo_ingest.crawl.browser import BrowserFetcher, HostBrowserConfig

    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.wait_for_selector = AsyncMock()
    config = HostBrowserConfig(navigation_referer="https://nfa.kspo.or.kr/", timeout_ms=60000)
    await BrowserFetcher()._goto_ready(page, "https://nfa.kspo.or.kr/beforeReserve.kspo", config)
    assert page.goto.call_args.kwargs["referer"] == "https://nfa.kspo.or.kr/"
    assert page.goto.call_args.kwargs["timeout"] == 60000


@pytest.mark.asyncio
async def test_nfa_direct_entry_preserves_query_without_warmup_or_post():
    url = "https://nfa.kspo.or.kr/intro/intro.kspo?menuId=123"
    page = _make_page(url=url, content="<main>Public introduction</main>")
    ctx = _make_context(page)
    fetcher = BrowserFetcher()
    fetcher._browser = _make_browser(ctx)
    result = await fetcher.fetch(url)
    assert page.goto.await_count == 1
    assert page.goto.call_args.args[0] == url
    page.evaluate.assert_not_awaited()
    assert result.url == url
    assert b"Public introduction" in result.raw_bytes


@pytest.mark.asyncio
async def test_nfa_gate_only_when_redirected_and_reopens_requested_detail():
    import asyncio

    url = "https://nfa.kspo.or.kr/intro/intro.kspo?menuId=123"
    page = _make_page(url="https://nfa.kspo.or.kr/beforeReserve.kspo?isLogin=false")
    link = MagicMock()
    link.click = AsyncMock(
        side_effect=lambda: setattr(page, "url", "https://nfa.kspo.or.kr/main.kspo")
    )
    page.query_selector = AsyncMock(return_value=link)
    nav = MagicMock()
    nav.value = asyncio.get_running_loop().create_future()
    nav.value.set_result(_make_response())
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=nav)
    cm.__aexit__ = AsyncMock(return_value=False)
    page.expect_navigation.return_value = cm
    page.goto = AsyncMock(
        side_effect=lambda *a, **kw: setattr(page, "url", a[0]) or _make_response()
    )
    fetcher = BrowserFetcher()
    await fetcher._follow_entry_gate(page, url, DEFAULT_HOST_CONFIGS["nfa.kspo.or.kr"], None)
    link.click.assert_awaited_once()
    assert page.goto.call_args.args[0] == url
    assert page.url == url


@pytest.mark.asyncio
async def test_nfa_unresolved_gate_fails_instead_of_indexing_reservation_screen():
    page = _make_page(url="https://nfa.kspo.or.kr/beforeReserve.kspo")
    with pytest.raises(RuntimeError, match="no public main-page link"):
        await BrowserFetcher()._follow_entry_gate(
            page,
            "https://nfa.kspo.or.kr/intro/intro.kspo",
            DEFAULT_HOST_CONFIGS["nfa.kspo.or.kr"],
            None,
        )


@pytest.mark.asyncio
async def test_dynamic_failure_cannot_replace_valid_content_url():
    page = _make_page(url="https://example.com/main", content="<body>Valid public content</body>")
    fetcher = BrowserFetcher()
    session = _HostSession(
        ctx=_make_context(page),
        page=page,
        config=HostBrowserConfig(),
        profile=get_profile("chrome_win"),
    )

    async def failed_expansion(page, **kwargs):
        content = await page.content()
        page.url = "chrome-error://chromewebdata/"
        return content, {"failures": ["restore:TimeoutError"]}

    with patch("kspo_ingest.crawl.browser.expand_readonly", side_effect=failed_expansion):
        result = await fetcher._fetch_goto(session, "https://example.com/", 0)
    assert result.url == "https://example.com/main"
    assert b"Valid public content" in result.raw_bytes
    assert result.discovery_report["failures"]
