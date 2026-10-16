"""Validated crawl entry points shared by full and incremental jobs."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def parse_start_url(raw: str) -> str:
    text = raw.strip()
    if "://" not in text:
        text = "https://" + text.lstrip("/")
    p = urlsplit(text)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("Invalid HTTP(S) start URL")
    if p.port not in (None, 80, 443):
        raise ValueError("Unsupported start URL port")
    return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def entry_urls(domain, job=None) -> list[str]:
    urls = getattr(job, "seed_urls", None) or [
        getattr(domain, "start_url", None) or f"{domain.scheme}://{domain.host}/"
    ]
    result = []
    for raw in urls:
        url = parse_start_url(raw)
        if urlsplit(url).hostname != domain.host:
            raise ValueError("Start URL must match the registered domain")
        if url not in result:
            result.append(url)
    return result


def browser_required(domain) -> bool:
    return bool(domain.use_playwright or domain.host == "nfa.kspo.or.kr")


async def preflight_start(ctx, domain, urls):
    """Abort before destructive full reset if any entry cannot be read."""
    from selectolax.parser import HTMLParser

    from kspo_ingest.crawl.external_fetch import validate_destination
    from kspo_ingest.crawl.url_class import is_non_content_url

    smart = ctx.get("smart_fetcher")
    # Once per job preflight, not once per page or seed URL. Healthy profiles stay cached.
    reset_failed = getattr(smart, "reset_failed_profile", None)
    if reset_failed is not None:
        reset_failed(domain.host)

    for url in urls:
        await validate_destination(url)
        await ctx["rate_limit"].acquire(domain.host, float(domain.rate_limit_rps or 1.5))
        smart = ctx.get("smart_fetcher")
        if smart and callable(getattr(type(smart), "fetch_preflight", None)):
            result = await smart.fetch_preflight(url, user_agent=domain.user_agent)
        elif smart:
            result = await smart.fetch(
                url, user_agent=domain.user_agent, force_browser=browser_required(domain)
            )
        else:
            fetcher = ctx.get("playwright_fetcher") if browser_required(domain) else ctx["fetcher"]
            if fetcher is None:
                raise RuntimeError("Browser fetcher unavailable")
            result = await fetcher.fetch(url, user_agent=domain.user_agent)
        if result.http_status >= 400:
            raise RuntimeError(
                f"Start page HTTP error: status={result.http_status}, final_url={result.url}"
            )
        if urlsplit(result.url).hostname != domain.host:
            raise RuntimeError(
                f"Start page redirected outside domain: expected={domain.host}, "
                f"status={result.http_status}, final_url={result.url}"
            )
        if is_non_content_url(result.url):
            raise RuntimeError("Start page redirected to authentication")
        html = HTMLParser(result.raw_bytes)
        for node in html.css("script,style,noscript"):
            node.decompose()
        if len(html.text(strip=True)) < 10 or not html.css("a[href],button,[role=tab]"):
            raise RuntimeError("Start page has no readable content or navigation")
