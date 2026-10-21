"""Browser-based fetcher — Playwright + Stealth 통합.

기존 playwright_fetcher.py를 범용화:
- StealthProfile 기반 fingerprint 위장
- 호스트별 BrowserContext 풀링
- JS 네비게이션 / SPA 대응
- 페이지 대기 전략 설정 가능
- DOM 스냅샷 추출 (agent 연동용)

기존 _HOST_CONFIG 패턴은 호환 유지하되, 설정 기반으로 분리.
"""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright.async_api import TimeoutError as BrowserTimeoutError

from kspo_ingest.crawl.dynamic import expand_readonly
from kspo_ingest.crawl.fetcher import FetchResult
from kspo_ingest.crawl.readiness import ContentWaiter, ReadinessPolicy, wait_initial_content
from kspo_ingest.crawl.stealth import StealthProfile, apply_stealth, get_profile
from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "browser")


@dataclass
class HostBrowserConfig:
    """호스트별 브라우저 설정."""

    warmup_url: str | None = None
    click_selector: str | None = None
    needs_js_nav: bool = False
    wait_until: str = "domcontentloaded"
    timeout_ms: int = 30000
    readiness_policy: ReadinessPolicy | None = None
    navigation_referer: str | None = None
    stealth_profile: str | None = None  # StealthProfile 이름


# KSPO 특화 설정 — 기존 호환
DEFAULT_HOST_CONFIGS: dict[str, HostBrowserConfig] = {
    "nfa.kspo.or.kr": HostBrowserConfig(
        click_selector='a[href="/main.kspo"]',
        navigation_referer="https://nfa.kspo.or.kr/",
        timeout_ms=60000,
        stealth_profile="chrome_win",
    ),
}


@dataclass
class _HostSession:
    ctx: BrowserContext
    page: Page
    config: HostBrowserConfig
    profile: StealthProfile


class BrowserFetcher:
    """Playwright 브라우저 fetcher — Stealth + 호스트별 세션 관리.

    개선사항 (vs PlaywrightFetcher):
    - StealthProfile 기반 fingerprint 위장
    - 범용 호스트 설정 (HostBrowserConfig)
    - DOM 스냅샷 추출 메서드
    - 프록시 지원
    - 설정 기반 대기 전략
    """

    def __init__(
        self,
        *,
        host_configs: dict[str, HostBrowserConfig] | None = None,
        default_profile: str | None = None,
        proxy: str | None = None,
        headless: bool = True,
        dynamic_max_actions: int = 100,
        dynamic_timeout_seconds: float = 30.0,
        readiness_policy: ReadinessPolicy | None = None,
    ) -> None:
        self._host_configs = {**DEFAULT_HOST_CONFIGS, **(host_configs or {})}
        self._default_profile_name = default_profile
        self._proxy = proxy
        self._navigation_cache: dict[str, set[str]] = {}
        self._headless = headless
        if dynamic_max_actions < 1:
            raise ValueError("dynamic_max_actions must be positive")
        self._dynamic_max_actions = dynamic_max_actions
        if dynamic_timeout_seconds <= 0:
            raise ValueError("dynamic_timeout_seconds must be positive")
        self._dynamic_timeout_seconds = dynamic_timeout_seconds
        self._readiness_policy = readiness_policy or ReadinessPolicy()
        self._pw: Any = None
        self._browser: Browser | None = None
        self._sessions: dict[str, _HostSession] = {}

    async def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        self._pw = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": self._headless}
        if self._proxy:
            launch_kwargs["proxy"] = {"server": self._proxy}
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        log.bind(event="browser_launched", headless=self._headless).info("browser launched")

    async def _goto_ready(self, page: Page, url: str, config: HostBrowserConfig):
        policy = config.readiness_policy or self._readiness_policy
        waiter = ContentWaiter(page, policy)
        waiter.host = urlparse(url).hostname
        waiter.start()
        try:
            try:
                options = (
                    {"referer": config.navigation_referer} if config.navigation_referer else {}
                )
                response = await page.goto(
                    url, wait_until=config.wait_until, timeout=config.timeout_ms, **options
                )
            except BrowserTimeoutError:
                if urlparse(page.url).netloc != urlparse(url).netloc:
                    raise
                # A committed document can still become ready after navigation timeout.
                response = None
            await waiter.wait(initial=True)
            return response
        finally:
            waiter.close()

    async def _get_session(self, host: str) -> _HostSession:
        if host in self._sessions:
            return self._sessions[host]

        await self._ensure_browser()
        assert self._browser is not None

        config = self._host_configs.get(host, HostBrowserConfig())
        profile = get_profile(config.stealth_profile or self._default_profile_name)

        ctx = await self._browser.new_context(**profile.to_context_kwargs())
        page = await ctx.new_page()
        await apply_stealth(page, profile)

        # warmup
        if config.warmup_url:
            try:
                await self._goto_ready(page, config.warmup_url, config)
            except Exception:
                await ctx.close()
                raise
            if config.click_selector:
                link = await page.query_selector(config.click_selector)
                if link:
                    await link.click()
                    await page.wait_for_load_state(config.wait_until, timeout=config.timeout_ms)
            log.bind(event="session_warmup_ok", host=host).info("session warmed")

        session = _HostSession(ctx=ctx, page=page, config=config, profile=profile)
        self._sessions[host] = session
        return session

    async def fetch(
        self, url: str, *, user_agent: str | None = None, explore: bool = True
    ) -> FetchResult:
        """URL을 Playwright로 렌더링 후 FetchResult 반환."""
        started = time.perf_counter()
        host = urlparse(url).netloc.lower()
        session = await self._get_session(host)

        if session.config.needs_js_nav:
            return await self._fetch_js_nav(session, url, started, explore=explore)
        return await self._fetch_goto(session, url, started, explore=explore)

    async def _fetch_goto(
        self, session: _HostSession, url: str, started: float, *, explore: bool = True
    ) -> FetchResult:
        page = await session.ctx.new_page()
        await apply_stealth(page, session.profile)
        initial_responses = []

        def remember_response(response):
            if response.request.resource_type in ("xhr", "fetch") and len(initial_responses) < 200:
                initial_responses.append(response)

        page.on("response", remember_response)
        try:
            resp = await self._goto_ready(page, url, session.config)
            resp = await self._follow_entry_gate(page, url, session.config, resp)
            # 콘텐츠 로딩 대기
            with contextlib.suppress(Exception):
                await page.wait_for_selector(
                    "body :not(script):not(style):not(link)",
                    timeout=5000,
                )

            content_url = page.url
            headers = (
                {h["name"].lower(): h["value"] for h in await resp.headers_array()} if resp else {}
            )
            status = resp.status if resp else 200
            if explore and status < 400:
                content, discovery_report = await expand_readonly(
                    page,
                    max_actions=self._dynamic_max_actions,
                    max_elapsed_seconds=self._dynamic_timeout_seconds,
                    initial_responses=initial_responses,
                    navigation_cache=self._navigation_cache,
                    readiness_policy=session.config.readiness_policy or self._readiness_policy,
                )
            else:
                content = await page.content()
                discovery_report = {
                    "mode": "preflight" if not explore else "http_error",
                    "clicked": 0,
                }
            raw_bytes = content.encode("utf-8")
            status = resp.status if resp else 200
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            log.bind(
                event="browser_fetch_ok",
                url=url,
                status=status,
                size=len(raw_bytes),
                elapsed_ms=elapsed_ms,
            ).info("fetched")

            return FetchResult(
                url=content_url,
                http_status=status,
                content_type=headers.get("content-type", "text/html"),
                raw_bytes=raw_bytes,
                headers=headers,
                elapsed_ms=elapsed_ms,
                discovery_report=discovery_report,
            )
        finally:
            page.remove_listener("response", remember_response)
            await page.close()

    async def _follow_entry_gate(self, page, requested_url, config, response):
        """Only handle the NFA reservation gate after a real navigation to it."""
        current = urlparse(page.url)
        if current.hostname != "nfa.kspo.or.kr" or current.path != "/beforeReserve.kspo":
            return response
        link = await page.query_selector(config.click_selector or 'a[href="/main.kspo"]')
        if link is None:
            raise RuntimeError("NFA entry gate has no public main-page link")
        async with page.expect_navigation(
            wait_until=config.wait_until, timeout=config.timeout_ms
        ) as nav:
            await link.click()
        response = await nav.value
        await wait_initial_content(page, config.readiness_policy or self._readiness_policy)
        requested = urlparse(requested_url)
        if requested.path not in ("/", "/main.kspo", "/beforeReserve.kspo"):
            response = await self._goto_ready(page, requested_url, config)
        if urlparse(page.url).path == "/beforeReserve.kspo":
            raise RuntimeError("NFA entry gate did not release the requested page")
        return response

    async def _fetch_js_nav(
        self, session: _HostSession, url: str, started: float, *, explore: bool = True
    ) -> FetchResult:
        page = session.page
        parsed = urlparse(url)
        path = parsed.path

        try:
            async with page.expect_navigation(
                wait_until=session.config.wait_until,
                timeout=session.config.timeout_ms // 2,
            ):
                await page.evaluate(
                    f"""() => {{
                        var frm = document.createElement("form");
                        frm.method = "post";
                        frm.action = "{path}";
                        frm.innerHTML = "<input type='hidden' name='menuId' value=''/>";
                        document.body.append(frm);
                        frm.submit();
                    }}"""
                )
        except Exception:
            await page.wait_for_timeout(2000)

        await wait_initial_content(page, session.config.readiness_policy or self._readiness_policy)
        content_url = page.url
        if explore:
            content, discovery_report = await expand_readonly(
                page,
                max_actions=self._dynamic_max_actions,
                max_elapsed_seconds=self._dynamic_timeout_seconds,
                capture_initial=False,
                navigation_cache=self._navigation_cache,
                readiness_policy=session.config.readiness_policy or self._readiness_policy,
            )
        else:
            content = await page.content()
            discovery_report = {"mode": "preflight", "clicked": 0}
        raw_bytes = content.encode("utf-8")
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        log.bind(
            event="browser_js_nav_ok",
            url=url,
            size=len(raw_bytes),
            elapsed_ms=elapsed_ms,
        ).info("js nav fetched")

        return FetchResult(
            url=content_url,
            http_status=200,
            content_type="text/html",
            raw_bytes=raw_bytes,
            headers={},
            elapsed_ms=elapsed_ms,
            discovery_report=discovery_report,
        )

    async def get_dom_snapshot(self, url: str) -> dict[str, Any]:
        """페이지 DOM 스냅샷 추출 — Agent 연동용.

        반환:
        - html: 전체 HTML
        - title: 페이지 제목
        - url: 최종 URL
        - interactive_elements: 클릭 가능한 요소 목록
        """
        host = urlparse(url).netloc.lower()
        session = await self._get_session(host)
        page = await session.ctx.new_page()
        await apply_stealth(page, session.profile)

        try:
            await self._goto_ready(page, url, HostBrowserConfig())
            html = await page.content()
            title = await page.title()

            # 인터랙션 가능한 요소 추출
            elements = await page.evaluate("""() => {
                const items = [];
                const selectors = (
                    'a[href], button, input, select, textarea, [onclick], [role="button"]'
                );
                document.querySelectorAll(selectors).forEach((el, i) => {
                    if (i >= 100) return;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 && rect.height === 0) return;
                    items.push({
                        tag: el.tagName.toLowerCase(),
                        text: (el.textContent || '').trim().slice(0, 100),
                        href: el.getAttribute('href') || '',
                        type: el.getAttribute('type') || '',
                        name: el.getAttribute('name') || '',
                        id: el.getAttribute('id') || '',
                        class: el.getAttribute('class') || '',
                        index: i,
                    });
                });
                return items;
            }""")

            return {
                "html": html,
                "title": title,
                "url": page.url,
                "interactive_elements": elements,
            }
        finally:
            await page.close()

    async def execute_action(self, page: Page, action: str, **kwargs: Any) -> dict[str, Any]:
        """페이지에서 단일 액션 실행 — Agent tools에서 호출.

        지원 액션: click, type, scroll, select, wait, screenshot, extract_text
        """
        result: dict[str, Any] = {"action": action, "success": True}

        waiter = None
        before = None
        if action in ("click", "select"):
            waiter = ContentWaiter(page, self._readiness_policy).start()
        try:
            if waiter:
                before = await waiter.snapshot()
            if action == "click":
                selector = kwargs.get("selector", "")
                await page.click(selector, timeout=5000)

            elif action == "type":
                selector = kwargs.get("selector", "")
                text = kwargs.get("text", "")
                await page.fill(selector, text)

            elif action == "scroll":
                direction = kwargs.get("direction", "down")
                amount = kwargs.get("amount", 300)
                if direction == "down":
                    await page.evaluate(f"window.scrollBy(0, {amount})")
                else:
                    await page.evaluate(f"window.scrollBy(0, -{amount})")

            elif action == "select":
                selector = kwargs.get("selector", "")
                value = kwargs.get("value", "")
                await page.select_option(selector, value)

            elif action == "wait":
                ms = kwargs.get("ms", 1000)
                await page.wait_for_timeout(ms)

            elif action == "screenshot":
                data = await page.screenshot(type="png")
                result["screenshot_bytes"] = data

            elif action == "extract_text":
                selector = kwargs.get("selector", "body")
                element = await page.query_selector(selector)
                if element:
                    result["text"] = await element.text_content()
                else:
                    result["text"] = ""

            elif action == "goto":
                url = kwargs.get("url", "")
                await self._goto_ready(page, url, HostBrowserConfig())

            else:
                result["success"] = False
                result["error"] = f"Unknown action: {action}"

            if waiter:
                result["readiness"] = await waiter.wait(initial=False, before=before)
        finally:
            if waiter:
                waiter.close()

        return result

    def register_host_config(self, host: str, config: HostBrowserConfig) -> None:
        """동적으로 호스트 설정 추가."""
        self._host_configs[host] = config

    async def close(self) -> None:
        for session in self._sessions.values():
            try:
                await session.page.close()
                await session.ctx.close()
            except Exception:
                pass
        self._sessions.clear()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        log.bind(event="browser_closed").info("browser closed")
