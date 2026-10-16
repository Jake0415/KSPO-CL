"""패밀리사이트 크롤링 테스트 v2 — SmartFetcher + DomainProfiler 통합.

SmartFetcher가 JS redirect를 자동 감지·추적하여 이전 테스트 대비 개선된 결과 확인.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from kspo_ingest.crawl.domain_profile import CrawlStrategy, DomainProfiler, HealthStatus
from kspo_ingest.crawl.fetcher import Fetcher
from kspo_ingest.crawl.session_mgr import SessionManager
from kspo_ingest.crawl.smart_fetcher import SmartFetcher
from kspo_ingest.crawl.sitemap import discover_sitemap_urls

FAMILY_SITES: list[dict[str, str]] = [
    {"host": "www.kspo.or.kr", "name": "KSPO 본사"},
    {"host": "www.sports.re.kr", "name": "한국스포츠정책과학원"},
    {"host": "www.ksponco.or.kr", "name": "한국체육산업개발"},
    {"host": "www.kcycle.or.kr", "name": "경륜"},
    {"host": "www.kboat.or.kr", "name": "경정"},
    {"host": "www.spoex.com", "name": "스포엑스"},
    {"host": "www.spoinfo.or.kr", "name": "체육시설알리미"},
    {"host": "www.parktel.co.kr", "name": "올림픽파크텔"},
    {"host": "www.ecolian.or.kr", "name": "에콜리안"},
    {"host": "nfa.kspo.or.kr", "name": "국민체력100"},
    # 검증용: 접근 불가 사이트
    {"host": "www.spoex.or.kr", "name": "스포엑스(구)"},
    {"host": "nest.kspo.or.kr", "name": "올림픽공원NEST"},
]

MAX_DEPTH = 2
MAX_URLS_PER_DEPTH = 5


def extract_links_simple(html: str, host: str) -> list[str]:
    from selectolax.parser import HTMLParser
    import os
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []
    skip_exts = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".css", ".js",
                 ".pdf", ".docx", ".xlsx", ".zip", ".hwp", ".mp4")
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if href.startswith("/"):
            href = f"https://{host}{href}"
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != host.lower():
            continue
        _, ext = os.path.splitext(parsed.path)
        if ext.lower() in skip_exts:
            continue
        key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if key in seen:
            continue
        seen.add(key)
        out.append(href)
    return out


async def crawl_site(site: dict, smart: SmartFetcher, profiler: DomainProfiler):
    host = site["host"]
    name = site["name"]
    root_url = f"https://{host}/"

    # Step 1: Domain probe
    profile = await profiler.probe(host)
    print(f"\n{'='*80}")
    print(f"  {name} ({host})")
    print(f"{'='*80}")
    print(f"  Strategy     : {profile.strategy.value}")
    print(f"  Health       : {profile.health.value}")
    print(f"  HTTP Status  : {profile.http_status}")
    if profile.js_redirect:
        print(f"  JS Redirect  : {profile.js_redirect_target}")
    if profile.meta_refresh:
        print(f"  Meta Refresh : {profile.meta_refresh_target}")
    if profile.is_spa:
        print(f"  SPA          : Yes")
    if profile.has_canonical:
        print(f"  Canonical    : {profile.canonical_url}")
    if profile.has_sitemap:
        print(f"  Sitemap      : {profile.sitemap_urls}")
    if profile.final_url != root_url:
        print(f"  Final URL    : {profile.final_url}")
    print(f"  Content Size : {profile.content_size:,}B")
    print(f"  Response Time: {profile.response_time_ms}ms")
    print(f"  Int. Links   : {profile.internal_links_count}")
    if profile.error:
        print(f"  Error        : {profile.error}")

    if profile.strategy in (CrawlStrategy.UNREACHABLE,):
        print(f"  --> SKIP (unreachable)")
        return {
            "host": host, "name": name, "strategy": profile.strategy.value,
            "health": profile.health.value, "status": profile.http_status,
            "depth": 0, "pages": 0, "links": 0, "error": profile.error,
        }

    # Step 2: BFS crawl with SmartFetcher
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(root_url, 0)]
    results = []
    total_links = 0

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"

    while queue:
        url, depth = queue.pop(0)
        if url in visited or depth > MAX_DEPTH:
            continue
        depth_count = sum(1 for r in results if r["depth"] == depth)
        if depth_count >= MAX_URLS_PER_DEPTH:
            continue
        visited.add(url)

        try:
            result = await smart.fetch(url, user_agent=ua)
            html = result.raw_bytes.decode("utf-8", errors="replace")

            from selectolax.parser import HTMLParser
            tree = HTMLParser(html)
            title_el = tree.css_first("title")
            title = title_el.text(strip=True)[:60] if title_el else ""

            links = extract_links_simple(html, host)
            total_links += len(links)

            results.append({
                "url": result.url, "depth": depth, "status": result.http_status,
                "size": len(result.raw_bytes), "title": title, "links": len(links),
                "elapsed_ms": result.elapsed_ms,
            })

            print(f"\n  [depth={depth}] [{result.http_status}] {result.url}")
            print(f"    Title: {title}")
            print(f"    Size: {len(result.raw_bytes):,}B  Links: {len(links)}  Time: {result.elapsed_ms}ms")

            if depth < MAX_DEPTH:
                for link in links[:10]:
                    if link not in visited:
                        queue.append((link, depth + 1))

        except Exception as e:
            print(f"\n  [depth={depth}] FAIL {url}: {e}")
            results.append({
                "url": url, "depth": depth, "status": 0,
                "size": 0, "title": "", "links": 0, "error": str(e)[:100],
            })

    max_depth = max((r["depth"] for r in results), default=0)
    return {
        "host": host, "name": name, "strategy": profile.strategy.value,
        "health": profile.health.value, "status": profile.http_status,
        "depth": max_depth, "pages": len(results), "links": total_links,
        "error": profile.error,
    }


async def main():
    print("=" * 80)
    print("  KSPO 패밀리사이트 크롤링 테스트 v2 — SmartFetcher")
    print(f"  Max Depth: {MAX_DEPTH}  |  Max URLs/Depth: {MAX_URLS_PER_DEPTH}")
    print("=" * 80)

    session_mgr = SessionManager()
    fetcher = Fetcher(session_manager=session_mgr)
    profiler = DomainProfiler()
    smart = SmartFetcher(http_fetcher=fetcher, profiler=profiler, auto_probe=False)

    summaries = []
    for i, site in enumerate(FAMILY_SITES, 1):
        print(f"\n[{i}/{len(FAMILY_SITES)}] Probing & crawling {site['name']}...")
        summary = await crawl_site(site, smart, profiler)
        summaries.append(summary)

    # Summary table
    print(f"\n\n{'='*90}")
    print("  SUMMARY v2")
    print(f"{'='*90}")
    print(f"{'Site':<24} {'Strategy':<12} {'Health':<10} {'Status':>6} {'Depth':>5} {'Pages':>5} {'Links':>6}")
    print("-" * 90)
    ok = 0
    for s in summaries:
        icon = "✅" if s["health"] == "healthy" else "❌"
        status_str = str(s["status"]) if s["status"] else "FAIL"
        print(f"{icon} {s['name']:<22} {s['strategy']:<12} {s['health']:<10} "
              f"{status_str:>6} {s['depth']:>5} {s['pages']:>5} {s['links']:>6}")
        if s["health"] == "healthy":
            ok += 1
    print("-" * 90)
    print(f"Total: {ok}/{len(summaries)} sites healthy")

    await smart.close()


if __name__ == "__main__":
    asyncio.run(main())
