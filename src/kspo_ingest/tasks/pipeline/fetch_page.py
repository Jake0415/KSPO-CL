"""fetch_page ARQ task — frontier dequeue + http fetch + raw 저장.

v2: SmartFetcher 통합 — 자동 전략 선택 (httpx/browser).
    기존 use_playwright 플래그도 하위 호환 유지.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from kspo_ingest.attach.discovery import is_attachment_url, is_binary_content
from kspo_ingest.crawl.external_fetch import fetch_external, validate_destination
from kspo_ingest.crawl.fetcher import ResponseTooLargeError
from kspo_ingest.crawl.start_url import browser_required
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled
from kspo_ingest.tasks.pipeline.helpers import (
    get_domain,
    get_or_create_page,
    mark_dropped,
    mark_error,
    mark_fetched,
    save_raw,
)
from kspo_ingest.tasks.pipeline.orphan import handle_404

log = get_logger("worker", "fetch_page")


async def fetch_page(ctx: dict, *, job_id: int, domain_id: int, url: str, depth: int) -> int | None:
    """returns page_id (성공) or None (skip/fail). 후속 task는 호출자(enqueue_seeds)가 결선."""
    session_factory = ctx["session_factory"]
    storage_root = ctx["storage_root"]
    robots = ctx["robots"]
    rate_limit = ctx["rate_limit"]

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return None

        page = await get_or_create_page(s, domain_id=domain_id, url=url, depth=depth)
        domain = await get_domain(s, domain_id)
        if domain is None:
            return None

        if is_attachment_url(url):
            await mark_dropped(s, page.id, reason="attachment_metadata_only")
            await bump_stats(s, job_id, dropped=1, drop_reasons__attachment_metadata_only=1)
            return None

        ua = domain.user_agent or settings.crawl_user_agent_default

        external = urlsplit(url).hostname != domain.host
        if external:
            try:
                await validate_destination(url)
            except (ValueError, OSError) as exc:
                await mark_error(s, page.id, error=str(exc))
                await bump_stats(s, job_id, errors=1)
                return None

        # robots.txt 체크 (옵션)
        if domain.respect_robots:
            allowed = await robots.is_allowed(url, ua)
            if not allowed:
                await mark_dropped(s, page.id, reason="robots")
                await bump_stats(s, job_id, dropped=1, drop_reasons__robots=1)
                log.bind(event="fetch_skip_robots", page_id=page.id).info("robots disallow")
                return None

        # rate limit
        await rate_limit.acquire(
            urlsplit(url).hostname or domain.host, float(domain.rate_limit_rps or 1.5)
        )

        # Fetcher 선택: SmartFetcher > use_playwright > httpx
        smart = ctx.get("smart_fetcher")
        if external:
            try:
                result = await fetch_external(url, user_agent=ua)
            except Exception as exc:
                await mark_error(s, page.id, error=f"external_fetch: {type(exc).__name__}")
                await bump_stats(s, job_id, errors=1)
                return None
        elif smart:
            # SmartFetcher — 자동 전략 선택
            try:
                result = await smart.fetch(
                    url, user_agent=ua, force_browser=browser_required(domain)
                )
            except ConnectionError as e:
                # UNREACHABLE domain
                await mark_error(s, page.id, error=f"unreachable: {e}")
                await bump_stats(s, job_id, errors=1)
                return None
            except ResponseTooLargeError as e:
                await mark_error(s, page.id, error=f"too_large: {e}")
                await bump_stats(s, job_id, errors=1)
                return None
            except Exception as e:
                await mark_error(s, page.id, error=str(e))
                await bump_stats(s, job_id, errors=1)
                if ctx.get("raise_fetch_errors"):
                    raise
                log.bind(event="fetch_error", page_id=page.id, error=str(e)).warning("fetch failed")
                return None
        else:
            # 하위 호환: use_playwright 또는 SmartFetcher 미등록
            fetcher = ctx["fetcher"]
            active_fetcher = ctx.get("playwright_fetcher") if browser_required(domain) else fetcher
            try:
                result = await active_fetcher.fetch(url, user_agent=ua)
            except ResponseTooLargeError as e:
                await mark_error(s, page.id, error=f"too_large: {e}")
                await bump_stats(s, job_id, errors=1)
                return None
            except Exception as e:
                await mark_error(s, page.id, error=str(e))
                await bump_stats(s, job_id, errors=1)
                if ctx.get("raise_fetch_errors"):
                    raise
                log.bind(event="fetch_error", page_id=page.id, error=str(e)).warning("fetch failed")
                return None

        if result.http_status == 404:
            removed = await handle_404(s, page_id=page.id, job_id=job_id)
            if removed:
                await bump_stats(s, job_id, removed=1)
            else:
                await bump_stats(s, job_id, errors=1)
            return None
        if result.http_status >= 400:
            await mark_error(s, page.id, error=f"http_{result.http_status}")
            await bump_stats(s, job_id, errors=1)
            return None

        if is_binary_content(result.raw_bytes, result.content_type):
            await mark_dropped(s, page.id, reason="attachment_metadata_only")
            await bump_stats(s, job_id, dropped=1, drop_reasons__attachment_metadata_only=1)
            return None

        if getattr(result, "discovery_report", None):
            page.storage_paths = {
                **(page.storage_paths or {}),
                "discovery_report": result.discovery_report,
            }
        page.storage_paths = {**(page.storage_paths or {}), "final_url": result.url}
        _, url_hash = normalize_url(url)
        save_raw(storage_root, domain_id, url_hash, result.raw_bytes)

        await mark_fetched(
            s, page.id, http_status=result.http_status, content_type=result.content_type
        )
        await bump_stats(s, job_id, fetched=1)
        log.bind(
            event="fetch_ok",
            page_id=page.id,
            url_hash=url_hash[:8],
            http_status=result.http_status,
            byte_size=len(result.raw_bytes),
            elapsed_ms=result.elapsed_ms,
        ).info("fetched")
        return page.id
