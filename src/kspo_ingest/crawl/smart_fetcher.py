"""SmartFetcher — httpx/Browser 자동 전략 선택 통합 fetcher.

기존 Fetcher + BrowserFetcher를 감싸서:
1. DomainProfiler로 도메인 probe
2. strategy에 따라 httpx 또는 Playwright 자동 선택
3. JS redirect 자동 감지·추적
4. Meta refresh 자동 처리
5. httpx 실패 시 Playwright 자동 승격
6. 응답 크기 기반 SPA 자동 감지
"""

from __future__ import annotations

import time
from urllib.parse import urlparse

from kspo_ingest.crawl.browser import BrowserFetcher
from kspo_ingest.crawl.domain_profile import (
    CrawlStrategy,
    DomainProfile,
    DomainProfiler,
    HealthStatus,
    detect_js_redirect,
    detect_meta_refresh,
)
from kspo_ingest.crawl.dynamic import has_dynamic_controls
from kspo_ingest.crawl.fetcher import Fetcher, FetchResult
from kspo_ingest.crawl.readiness import ContentReadinessError
from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "smart_fetcher")

# SSR 최소 body 크기 — 이 이하면 JS redirect 또는 빈 shell 의심
_MIN_SSR_BODY = 512

# SPA 감지: body에 <noscript>만 있거나 텍스트 콘텐츠 매우 적음
_MIN_TEXT_CONTENT = 200


class SmartFetcher:
    """자동 전략 선택 fetcher.

    사용법:
        fetcher = SmartFetcher()
        result = await fetcher.fetch(url, user_agent="...")
        # 자동으로 httpx 또는 Playwright 선택

    내부 흐름:
        1. DomainProfiler 캐시 확인 (이미 probe 된 도메인은 즉시 전략 결정)
        2. 캐시 없으면 probe 실행
        3. strategy에 따라:
           - HTTPX: httpx로 fetch → JS redirect/meta refresh 자동 follow
           - HTTPX_JS_FOLLOW: httpx로 JS redirect만 따라감
           - BROWSER: Playwright로 fetch
           - UNREACHABLE: 실제 입력 URL을 브라우저로 한 번 재시도
        4. httpx 결과가 빈 shell이면 Playwright로 자동 승격
    """

    def __init__(
        self,
        *,
        http_fetcher: Fetcher | None = None,
        browser_fetcher: BrowserFetcher | None = None,
        profiler: DomainProfiler | None = None,
        auto_probe: bool = True,
        render_all_html: bool = True,
    ) -> None:
        self._http = http_fetcher or Fetcher()
        self._browser = browser_fetcher
        self._profiler = profiler or DomainProfiler()
        self._auto_probe = auto_probe
        self._render_all_html = render_all_html
        self._owns_browser = browser_fetcher is None

    async def _ensure_browser(self) -> BrowserFetcher:
        if self._browser is None:
            self._browser = BrowserFetcher(headless=True)
            self._owns_browser = True
        return self._browser

    async def fetch_preflight(self, url: str, *, user_agent: str | None = None):
        """Validate rendered entry content without clicking discovery controls."""
        browser = await self._ensure_browser()
        # Never reuse a navigation discovery cache across separate crawl jobs.
        browser._navigation_cache.clear()
        return await browser.fetch(url, user_agent=user_agent, explore=False)

    async def _browser_or_http(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None = None,
    ) -> FetchResult:
        """Browser fetch, but degrade to plain HTTP if the browser is unavailable.

        A missing/broken Playwright install (headless_shell 미설치) must NOT lose a
        perfectly valid HTTP response — otherwise full-HTML sites wrongly profiled
        as BROWSER get recorded as ERROR (audit 2026-07-11: ksponco/parktel).
        """
        try:
            browser = await self._ensure_browser()
            return await browser.fetch(url, user_agent=user_agent)
        except ContentReadinessError:
            raise
        except Exception as e:
            log.bind(event="browser_unavailable_http_fallback", url=url, err=str(e)[:120]).warning(
                "browser 사용불가 — HTTP 폴백"
            )
            result = await self._http.fetch(url, user_agent=user_agent, proxy=proxy)
            result.discovery_report = {"needs_review": True, "failures": ["browser_unavailable"]}
            return result

    async def fetch(
        self,
        url: str,
        *,
        user_agent: str,
        force_browser: bool = False,
        proxy: str | None = None,
    ) -> FetchResult:
        """URL 페치 — 자동 전략 선택."""
        host = urlparse(url).netloc.lower()

        # 강제 브라우저 모드
        if force_browser:
            browser = await self._ensure_browser()
            return await browser.fetch(url, user_agent=user_agent)

        # 도메인 프로파일 확인
        profile = self._profiler.get_cached(host)
        if profile is None and self._auto_probe:
            profile = await self._profiler.probe(host)

        # 프로파일 기반 전략 결정
        if profile:
            if profile.strategy == CrawlStrategy.UNREACHABLE:
                log.bind(
                    event="probe_failed_browser_retry",
                    host=host,
                    health=profile.health.value,
                ).warning("root probe failed; trying requested URL in browser")
                # One direct attempt, not _browser_or_http: an actual browser
                # failure must propagate, rather than hide behind an HTTP fallback.
                browser = await self._ensure_browser()
                result = await browser.fetch(url, user_agent=user_agent)
                if (
                    200 <= result.http_status < 400
                    and urlparse(result.url).scheme in ("http", "https")
                    and urlparse(result.url).netloc.lower() == host
                ):
                    profile.strategy = CrawlStrategy.BROWSER
                    profile.health = HealthStatus.HEALTHY
                    profile.error = ""
                    profile.http_status = result.http_status
                    profile.final_url = result.url
                    profile.content_size = len(result.raw_bytes)
                    profile.probed_at = time.time()
                return result

            if profile.strategy == CrawlStrategy.BROWSER:
                return await self._browser_or_http(url, user_agent=user_agent, proxy=proxy)

            if profile.strategy == CrawlStrategy.HTTPX_JS_FOLLOW:
                return await self._fetch_with_auto_escalation(
                    url, user_agent=user_agent, proxy=proxy
                )

        # 기본: httpx + 자동 승격
        return await self._fetch_with_auto_escalation(
            url,
            user_agent=user_agent,
            proxy=proxy,
        )

    async def _fetch_with_js_follow(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None,
    ) -> FetchResult:
        """httpx로 fetch + JS redirect/meta refresh 자동 follow (최대 3단)."""
        current_url = url
        for _ in range(3):
            result = await self._http.fetch(current_url, user_agent=user_agent, proxy=proxy)

            if result.http_status >= 400:
                return result

            body = result.raw_bytes.decode("utf-8", errors="replace")

            # 작은 body면 JS redirect/meta refresh 확인
            if len(result.raw_bytes) < 2048:
                js_target = detect_js_redirect(body, result.url)
                if js_target:
                    log.bind(
                        event="js_redirect_follow", from_url=current_url, to_url=js_target
                    ).debug("following")
                    current_url = js_target
                    continue

                meta_target = detect_meta_refresh(body, result.url)
                if meta_target:
                    log.bind(
                        event="meta_refresh_follow", from_url=current_url, to_url=meta_target
                    ).debug("following")
                    current_url = meta_target
                    continue

            return result

        return result  # type: ignore[possibly-undefined]

    async def _fetch_with_auto_escalation(
        self,
        url: str,
        *,
        user_agent: str,
        proxy: str | None,
    ) -> FetchResult:
        """httpx로 fetch, 결과가 빈 shell이면 Playwright 자동 승격."""
        result = await self._fetch_with_js_follow(url, user_agent=user_agent, proxy=proxy)

        # 자동 승격 판단
        if self._should_escalate(result):
            log.bind(
                event="smart_fetch_escalate",
                url=url,
                reason="html_render_or_dynamic_controls",
                body_size=len(result.raw_bytes),
            ).info("escalating to browser")

            try:
                browser = await self._ensure_browser()
                browser_result = await browser.fetch(url, user_agent=user_agent)
            except ContentReadinessError:
                raise
            except Exception as e:
                # browser 승격 실패 → 이미 확보한 HTTP result로 폴백(내용 유실 방지)
                log.bind(
                    event="escalate_browser_failed_http_fallback", url=url, err=str(e)[:120]
                ).warning("browser 승격 실패 — HTTP 결과 유지")
                result.discovery_report = {
                    "needs_review": True,
                    "failures": ["browser_escalation_failed"],
                }
                return result

            # 프로파일 갱신
            host = urlparse(url).netloc.lower()
            profile = self._profiler.get_cached(host)
            if profile:
                profile.strategy = CrawlStrategy.BROWSER
                profile.is_spa = True

            return browser_result

        return result

    def _should_escalate(self, result: FetchResult) -> bool:
        """httpx 결과를 보고 Playwright 승격이 필요한지 판단."""
        if result.http_status >= 400:
            return False

        body = result.raw_bytes
        ct = result.content_type.lower()

        # HTML이 아니면 승격 불필요
        if "html" not in ct:
            return False

        if self._render_all_html:
            return True

        if has_dynamic_controls(body.decode("utf-8", errors="replace")):
            return True

        # body가 매우 작으면 빈 shell
        if len(body) < _MIN_SSR_BODY:
            return True

        # body 있지만 텍스트 콘텐츠가 너무 적으면 SPA
        try:
            from selectolax.parser import HTMLParser

            text = body.decode("utf-8", errors="replace")
            tree = HTMLParser(text)
            if tree.body:
                visible_text = tree.body.text(strip=True)
                if len(visible_text) < _MIN_TEXT_CONTENT and len(body) > 1000:
                    return True
        except Exception:
            pass

        return False

    def reset_failed_profile(self, host: str) -> None:
        self._profiler.invalidate_failed(host)

    async def probe_domain(self, host: str) -> DomainProfile:
        """명시적 도메인 probe."""
        return await self._profiler.probe(host, force=True)

    def get_profile(self, host: str) -> DomainProfile | None:
        return self._profiler.get_cached(host)

    async def close(self) -> None:
        await self._http.close()
        if self._owns_browser and self._browser:
            await self._browser.close()
