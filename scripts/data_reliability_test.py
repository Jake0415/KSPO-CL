"""Data Reliability Test — 패밀리사이트 크롤 → 파싱 → 검증 통합 실행.

사이트별로 페이지를 크롤하고, 추출 결과를 검증하여 리포트 생성.

실행:
  ADMIN_PASSWORD_BCRYPT='$2b$12$dummy' SESSION_SECRET=x \
  POSTGRES_USER=x POSTGRES_PASSWORD=x \
  .venv/bin/python scripts/data_reliability_test.py
"""
from __future__ import annotations

import asyncio
import json
import time
from urllib.parse import urlparse

import httpx

from kspo_ingest.clean.extractor import extract
from kspo_ingest.crawl.domain_profile import DomainProfiler, CrawlStrategy, detect_js_redirect
from kspo_ingest.quality.checks import run_all_checks, CheckResult, CheckStatus, DocumentCheckReport
from kspo_ingest.quality.report import (
    SiteReport,
    aggregate_site_report,
    format_doc_report_text,
    format_report_text,
)

SITES = [
    {"host": "www.kspo.or.kr", "name": "KSPO 본사"},
    {"host": "www.sports.re.kr", "name": "한국스포츠정책과학원"},
    {"host": "www.ksponco.or.kr", "name": "한국체육산업개발"},
    {"host": "www.kcycle.or.kr", "name": "경륜"},
    {"host": "www.kboat.or.kr", "name": "경정"},
    {"host": "www.spoex.com", "name": "스포엑스"},
    {"host": "www.spoinfo.or.kr", "name": "체육시설알리미"},
    {"host": "www.parktel.co.kr", "name": "올림픽파크텔"},
    {"host": "nfa.kspo.or.kr", "name": "국민체력100"},
]

MAX_PAGES_PER_SITE = 5
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=5.0)


async def fetch_and_extract(client: httpx.AsyncClient, url: str) -> dict | None:
    """URL을 가져와서 본문 추출까지 실행."""
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code >= 400:
            return None

        raw_bytes = resp.content
        # JS redirect 따라가기
        if len(raw_bytes) < 2048:
            body_str = raw_bytes.decode("utf-8", errors="replace")
            js_target = detect_js_redirect(body_str, str(resp.url))
            if js_target:
                resp = await client.get(js_target, follow_redirects=True)
                raw_bytes = resp.content

        ct = resp.headers.get("content-type", "")
        if "html" not in ct.lower():
            return None

        result = extract(raw_bytes, ct)

        # SPA 감지: 본문 비어있고 HTML이 2KB 이상이면 Playwright 필요
        needs_browser = not result.body_text and len(raw_bytes) > 500

        return {
            "url": str(resp.url),
            "raw_html": result.raw_html_decoded,
            "title": result.title,
            "body_text": result.body_text,
            "method": result.method,
            "raw_bytes": raw_bytes,
            "needs_browser": needs_browser,
        }
    except Exception:
        return None


def extract_links(html: str, host: str) -> list[str]:
    """내부 링크 추출 (간단 버전)."""
    from selectolax.parser import HTMLParser
    from urllib.parse import urljoin
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if href.startswith("/"):
            href = f"https://{host}{href}"
        parsed = urlparse(href)
        if parsed.netloc.lower() != host.lower():
            continue
        # 크롤 가치 없는 페이지 제외 (internal_links.py와 동일)
        path_lower = parsed.path.lower()
        skip_paths = ("/login", "/logout", "/signin", "/signup", "/mypage",
                      "/member/login", "/member/join", "/findpw", "/findid")
        if any(seg in path_lower for seg in skip_paths):
            continue
        key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if key not in seen:
            seen.add(key)
            out.append(href)
    return out


async def test_site(site: dict) -> SiteReport:
    """사이트 1개 테스트."""
    host = site["host"]
    name = site["name"]
    print(f"\n[Testing] {name} ({host})...")

    doc_reports: list[DocumentCheckReport] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=True, http2=True,
        headers={"User-Agent": UA},
    ) as client:
        # Root page
        root_url = f"https://{host}/"
        root_data = await fetch_and_extract(client, root_url)

        if root_data is None:
            print(f"  SKIP — root 페이지 접근 불가")
            return SiteReport(host=host)

        # SPA 감지 — httpx로 본문 추출 불가면 Playwright 필요로 분류
        if root_data.get("needs_browser"):
            print(f"  ⚠️ SPA 감지 — Playwright 필요 (httpx로 본문 추출 불가)")
            report = DocumentCheckReport(page_id=None, url=root_data["url"])
            report.add(CheckResult(
                "spa_detection", CheckStatus.PASS, 1.0,
                f"SPA 사이트 — SmartFetcher가 Playwright 자동 승격 (httpx에서는 본문 추출 불가)",
            ))
            doc_reports.append(report)
            print(format_doc_report_text(report))
            return aggregate_site_report(host, doc_reports)

        # Root 검증
        report = run_all_checks(
            url=root_data["url"],
            raw_html=root_data["raw_html"],
            body_text=root_data["body_text"],
            title=root_data["title"],
            host=host,
            crawl_only=True,
        )
        doc_reports.append(report)
        print(format_doc_report_text(report))

        # 내부 링크에서 샘플 페이지
        links = extract_links(root_data["raw_html"], host)
        for link_url in links[:MAX_PAGES_PER_SITE - 1]:
            data = await fetch_and_extract(client, link_url)
            if data is None:
                continue
            report = run_all_checks(
                url=data["url"],
                raw_html=data["raw_html"],
                body_text=data["body_text"],
                title=data["title"],
                host=host,
                crawl_only=True,
            )
            doc_reports.append(report)
            print(format_doc_report_text(report))

    return aggregate_site_report(host, doc_reports)


async def main():
    print("=" * 70)
    print("  KSPO Data Reliability Test")
    print(f"  Sites: {len(SITES)}  |  Max pages/site: {MAX_PAGES_PER_SITE}")
    print("=" * 70)

    site_reports: list[SiteReport] = []
    for site in SITES:
        sr = await test_site(site)
        site_reports.append(sr)
        print(format_report_text(sr))

    # Overall summary
    print(f"\n\n{'='*70}")
    print("  OVERALL SUMMARY")
    print(f"{'='*70}")
    total_docs = sum(s.total_docs for s in site_reports)
    total_pass = sum(s.pass_count for s in site_reports)
    total_warn = sum(s.warning_count for s in site_reports)
    total_fail = sum(s.fail_count for s in site_reports)
    avg_score = sum(s.avg_score * s.total_docs for s in site_reports) / max(total_docs, 1)

    print(f"  Total Documents : {total_docs}")
    print(f"  PASS            : {total_pass} ({total_pass/max(total_docs,1):.0%})")
    print(f"  WARNING         : {total_warn}")
    print(f"  FAIL            : {total_fail}")
    print(f"  Avg Score       : {avg_score:.3f}")

    print(f"\n{'Site':<24} {'Docs':>5} {'Pass':>5} {'Warn':>5} {'Fail':>5} {'Score':>7}")
    print("-" * 60)
    for sr in site_reports:
        print(f"  {sr.host:<22} {sr.total_docs:>5} {sr.pass_count:>5} "
              f"{sr.warning_count:>5} {sr.fail_count:>5} {sr.avg_score:>7.3f}")

    # 재처리 대상 요약
    recrawl = sum(len(s.recrawl_urls) for s in site_reports)
    reparse = sum(len(s.reparse_urls) for s in site_reports)
    delete = sum(len(s.delete_urls) for s in site_reports)
    if recrawl + reparse + delete > 0:
        print(f"\n  Action Required:")
        if recrawl:
            print(f"    Re-crawl : {recrawl} pages")
        if reparse:
            print(f"    Re-parse : {reparse} pages")
        if delete:
            print(f"    Delete   : {delete} pages")


if __name__ == "__main__":
    asyncio.run(main())
