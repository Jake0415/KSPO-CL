"""Domain Profile — 도메인별 크롤 전략을 자동 탐지·생성.

기존 _HOST_CONFIG 수동 설정을 대체:
1. probe() — 도메인에 httpx 요청 → 응답 패턴 분석
2. 자동 분류: JS redirect / SPA / SSR / meta refresh / static
3. 크롤 전략 자동 결정: httpx / browser / browser+vision
4. DomainHealth 통합: DNS/timeout/4xx/5xx 자동 분류

사용:
    profiler = DomainProfiler()
    profile = await profiler.probe("www.kcycle.or.kr")
    # profile.strategy == "httpx"  (JS redirect 후 SSR 페이지)
    # profile.js_redirect_target == "/main"
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from urllib.parse import urljoin

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("crawl", "domain_profile")


class CrawlStrategy(StrEnum):
    """크롤 전략."""

    HTTPX = "httpx"  # 정적 SSR — httpx 충분
    HTTPX_JS_FOLLOW = "httpx_js"  # JS redirect 후 SSR — httpx가 redirect 따라감
    BROWSER = "browser"  # SPA / 동적 렌더링 — Playwright 필요
    UNREACHABLE = "unreachable"  # DNS 실패, 타임아웃 등


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    DNS_FAIL = "dns_fail"
    TIMEOUT = "timeout"
    HTTP_ERROR = "http_error"  # 4xx/5xx
    SSL_ERROR = "ssl_error"
    UNKNOWN = "unknown"


@dataclass
class DomainProfile:
    """도메인 프로파일 — probe 결과."""

    host: str
    strategy: CrawlStrategy = CrawlStrategy.HTTPX
    health: HealthStatus = HealthStatus.UNKNOWN
    http_status: int = 0
    final_url: str = ""
    js_redirect: bool = False
    js_redirect_target: str = ""
    meta_refresh: bool = False
    meta_refresh_target: str = ""
    is_spa: bool = False
    has_canonical: bool = False
    canonical_url: str = ""
    content_size: int = 0
    response_time_ms: int = 0
    server: str = ""
    has_robots_txt: bool = False
    has_sitemap: bool = False
    sitemap_urls: list[str] = field(default_factory=list)
    error: str = ""
    probed_at: float = 0.0
    # redirect chain
    redirect_chain: list[str] = field(default_factory=list)
    # SSR 판단용: body에서 추출한 내부 링크 수
    internal_links_count: int = 0


# JS redirect 패턴
_JS_REDIRECT_PATTERNS = [
    re.compile(r"""location\.href\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""window\.location\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""window\.location\.replace\s*\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""location\.replace\s*\(\s*["']([^"']+)["']\s*\)"""),
    re.compile(r"""document\.location\s*=\s*["']([^"']+)["']"""),
    re.compile(r"""self\.location\s*=\s*["']([^"']+)["']"""),
]

# Meta refresh 패턴
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["']?\d+\s*;\s*url\s*=\s*["']?([^"'\s>]+)""",
    re.IGNORECASE,
)

# SPA 판별 패턴: body가 거의 빈 shell + JS bundle
_SPA_INDICATORS = [
    re.compile(r"""<div\s+id\s*=\s*["'](?:app|root|__next|__nuxt)["']""", re.IGNORECASE),
    re.compile(
        r"""<script[^>]*src\s*=\s*["'][^"']*(?:bundle|chunk|main)\.[a-f0-9]+\.js""",
        re.IGNORECASE,
    ),
]

# Canonical URL
_CANONICAL_RE = re.compile(
    r"""<link[^>]*rel\s*=\s*["']canonical["'][^>]*href\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)


def detect_js_redirect(body: str, base_url: str) -> str | None:
    """JS redirect 목적지 추출. 없으면 None."""
    for pattern in _JS_REDIRECT_PATTERNS:
        m = pattern.search(body)
        if m:
            target = m.group(1)
            return urljoin(base_url, target)
    return None


def detect_meta_refresh(body: str, base_url: str) -> str | None:
    """Meta refresh 목적지 추출."""
    m = _META_REFRESH_RE.search(body)
    if m:
        return urljoin(base_url, m.group(1))
    return None


def detect_canonical(body: str) -> str | None:
    """Canonical URL 추출."""
    m = _CANONICAL_RE.search(body)
    return m.group(1) if m else None


def detect_spa(body: str) -> bool:
    """SPA 여부 판별.

    기준:
    - body < 5KB + SPA indicator (app/root div, bundle.js)
    - 또는 body 내 text content가 매우 적고 script가 많음
    """
    if len(body) > 50_000:
        return False  # 큰 페이지는 SSR
    for pattern in _SPA_INDICATORS:
        if pattern.search(body):
            # SPA indicator 있고 텍스트 콘텐츠가 적으면 SPA
            from selectolax.parser import HTMLParser

            tree = HTMLParser(body)
            if tree.body:
                text = tree.body.text(strip=True)
                # 텍스트가 500자 미만이면 SPA
                if len(text) < 500:
                    return True
    return False


def count_internal_links(body: str, host: str) -> int:
    """내부 링크 수 카운트."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(body)
    count = 0
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if href.startswith("/") or host in href:
            count += 1
    return count


class DomainProfiler:
    """도메인 프로파일러 — probe로 자동 분석.

    사용:
        profiler = DomainProfiler()
        profile = await profiler.probe("www.kcycle.or.kr")
    """

    def __init__(self, *, failure_ttl_seconds: float = 60.0) -> None:
        if failure_ttl_seconds <= 0:
            raise ValueError("failure_ttl_seconds must be positive")
        self._failure_ttl_seconds = failure_ttl_seconds
        self._cache: dict[str, DomainProfile] = {}

    async def probe(self, host: str, *, force: bool = False) -> DomainProfile:
        """도메인을 probe하여 프로파일 생성."""
        cached = self.get_cached(host)
        if not force and cached is not None:
            return cached

        profile = DomainProfile(host=host, probed_at=time.time())
        root_url = f"https://{host}/"

        # Step 1: Root URL 요청 (redirect 미추적)
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=False,
                http2=True,
                headers={"User-Agent": _UA},
            ) as client:
                started = time.perf_counter()
                resp = await client.get(root_url)
                profile.response_time_ms = int((time.perf_counter() - started) * 1000)
                profile.http_status = resp.status_code
                profile.server = resp.headers.get("server", "")

                # HTTP redirect chain 따라가기
                chain = [root_url]
                current_resp = resp
                for _ in range(5):  # max 5 redirects
                    if current_resp.status_code in (301, 302, 303, 307, 308):
                        loc = current_resp.headers.get("location", "")
                        if loc:
                            loc = urljoin(str(current_resp.url), loc)
                            chain.append(loc)
                            current_resp = await client.get(loc)
                            profile.http_status = current_resp.status_code
                        else:
                            break
                    else:
                        break
                profile.redirect_chain = chain
                profile.final_url = str(current_resp.url)
                resp = current_resp

                body_bytes = resp.content
                profile.content_size = len(body_bytes)
                body = body_bytes.decode("utf-8", errors="replace")

        except httpx.ConnectError as e:
            err = str(e)
            if "nodename" in err or "getaddrinfo" in err or "Name or service" in err:
                profile.health = HealthStatus.DNS_FAIL
            else:
                profile.health = HealthStatus.UNKNOWN
            profile.strategy = CrawlStrategy.UNREACHABLE
            profile.error = err[:200]
            self._cache[host] = profile
            return profile

        except httpx.TimeoutException:
            profile.health = HealthStatus.TIMEOUT
            profile.strategy = CrawlStrategy.UNREACHABLE
            profile.error = "timeout"
            self._cache[host] = profile
            return profile

        except Exception as e:
            if "SSL" in type(e).__name__ or "ssl" in str(e).lower():
                profile.health = HealthStatus.SSL_ERROR
            else:
                profile.health = HealthStatus.UNKNOWN
            profile.strategy = CrawlStrategy.UNREACHABLE
            profile.error = str(e)[:200]
            self._cache[host] = profile
            return profile

        # Step 2: HTTP status 평가
        if profile.http_status >= 400:
            profile.health = HealthStatus.HTTP_ERROR
            profile.strategy = CrawlStrategy.UNREACHABLE
            profile.error = f"HTTP {profile.http_status}"
            self._cache[host] = profile
            return profile

        profile.health = HealthStatus.HEALTHY

        # Step 3: JS redirect 감지
        js_target = detect_js_redirect(body, profile.final_url)
        if js_target:
            profile.js_redirect = True
            profile.js_redirect_target = js_target
            # JS redirect 따라가서 결과 페이지 분석
            profile = await self._follow_js_redirect(profile, js_target)
            self._cache[host] = profile
            return profile

        # Step 4: Meta refresh 감지
        meta_target = detect_meta_refresh(body, profile.final_url)
        if meta_target:
            profile.meta_refresh = True
            profile.meta_refresh_target = meta_target

        # Step 5: Canonical URL 감지
        canonical = detect_canonical(body)
        if canonical:
            profile.has_canonical = True
            profile.canonical_url = canonical

        # Step 6: SPA 감지
        if detect_spa(body):
            profile.is_spa = True
            profile.strategy = CrawlStrategy.BROWSER
        else:
            profile.internal_links_count = count_internal_links(body, host)
            profile.strategy = CrawlStrategy.HTTPX

        # Step 7: robots.txt / sitemap 확인
        await self._check_robots_sitemap(profile)

        self._cache[host] = profile
        log.bind(
            event="domain_probed",
            host=host,
            strategy=profile.strategy.value,
            health=profile.health.value,
            js_redirect=profile.js_redirect,
            spa=profile.is_spa,
            links=profile.internal_links_count,
        ).info("domain probed")

        return profile

    async def _follow_js_redirect(
        self,
        profile: DomainProfile,
        target_url: str,
    ) -> DomainProfile:
        """JS redirect를 따라가서 결과 페이지 분석."""
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                http2=True,
                headers={"User-Agent": _UA},
            ) as client:
                resp = await client.get(target_url)

            body = resp.content.decode("utf-8", errors="replace")
            profile.content_size = len(resp.content)
            profile.final_url = str(resp.url)

            # redirect 후 페이지가 또 JS redirect인지
            nested_js = detect_js_redirect(body, str(resp.url))
            if nested_js:
                # 2단 JS redirect → Playwright 필요
                profile.strategy = CrawlStrategy.BROWSER
                return profile

            # SPA인지
            if detect_spa(body):
                profile.is_spa = True
                profile.strategy = CrawlStrategy.BROWSER
                return profile

            # SSR → httpx로 JS redirect만 따라가면 됨
            profile.internal_links_count = count_internal_links(body, profile.host)
            profile.strategy = CrawlStrategy.HTTPX_JS_FOLLOW

            # Canonical
            canonical = detect_canonical(body)
            if canonical:
                profile.has_canonical = True
                profile.canonical_url = canonical

        except Exception as e:
            # redirect 따라가기 실패 → Playwright로 fallback
            profile.strategy = CrawlStrategy.BROWSER
            profile.error = f"js_follow_fail: {str(e)[:100]}"

        return profile

    async def _check_robots_sitemap(self, profile: DomainProfile) -> None:
        """robots.txt 존재 확인 + sitemap URL 추출."""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0),
                follow_redirects=True,
                headers={"User-Agent": _UA},
            ) as client:
                robots_url = f"https://{profile.host}/robots.txt"
                resp = await client.get(robots_url)
                if resp.status_code == 200:
                    profile.has_robots_txt = True
                    text = resp.text
                    for line in text.splitlines():
                        line = line.strip()
                        if line.lower().startswith("sitemap:"):
                            sm_url = line.split(":", 1)[1].strip()
                            profile.sitemap_urls.append(sm_url)
                            profile.has_sitemap = True
        except Exception:
            pass

    def get_cached(self, host: str) -> DomainProfile | None:
        profile = self._cache.get(host)
        if (
            profile is not None
            and profile.strategy == CrawlStrategy.UNREACHABLE
            and time.time() - profile.probed_at >= self._failure_ttl_seconds
        ):
            self._cache.pop(host, None)
            return None
        return profile

    def invalidate_failed(self, host: str) -> None:
        """New crawl jobs must not inherit an earlier job's failed probe."""
        profile = self._cache.get(host)
        if profile is not None and profile.strategy == CrawlStrategy.UNREACHABLE:
            self._cache.pop(host, None)

    def get_all_cached(self) -> dict[str, DomainProfile]:
        return {
            host: profile
            for host in list(self._cache)
            if (profile := self.get_cached(host)) is not None
        }

    def clear_cache(self) -> None:
        self._cache.clear()
