"""JS리다이렉트/메타리프레시 진입점을 크롤 링크로 포함하는지 검증."""
from __future__ import annotations

from kspo_ingest.tasks.pipeline.extract_links import crawlable_link_urls


def test_js_redirect_target_included_when_no_anchor():
    html = '<html><head><script>location.href="/main.kspo";</script></head><body></body></html>'
    urls = crawlable_link_urls(html, base_url="https://sportsvalue.kspo.or.kr/", host="sportsvalue.kspo.or.kr")
    assert "https://sportsvalue.kspo.or.kr/main.kspo" in urls


def test_meta_refresh_target_included():
    html = '<html><head><meta http-equiv="refresh" content="0;url=/main/main.kspo"></head></html>'
    urls = crawlable_link_urls(html, base_url="https://sqms.kspo.or.kr/", host="sqms.kspo.or.kr")
    assert "https://sqms.kspo.or.kr/main/main.kspo" in urls


def test_external_redirect_excluded():
    # 다른 host로의 JS 리다이렉트는 제외 (ecolian -> www.ecolian.or.kr)
    html = '<html><head><script>location.href="https://www.ecolian.or.kr/";</script></head></html>'
    urls = crawlable_link_urls(html, base_url="https://ecolian.kspo.or.kr/", host="ecolian.kspo.or.kr")
    assert all("ecolian.or.kr/" not in u or "ecolian.kspo" in u for u in urls)
    assert "https://www.ecolian.or.kr/" not in urls


def test_anchor_links_still_work():
    html = '<html><body><a href="/page1.do">1</a><a href="/page2.do">2</a></body></html>'
    urls = crawlable_link_urls(html, base_url="https://www.kspo.or.kr/", host="www.kspo.or.kr")
    assert any("page1.do" in u for u in urls)
