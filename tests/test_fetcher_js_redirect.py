from __future__ import annotations

from kspo_ingest.crawl.domain_profile import detect_js_redirect


def test_detect_location_href():
    body = '<script>location.href = "/main";</script>'
    result = detect_js_redirect(body, "https://www.kcycle.or.kr/")
    assert result == "https://www.kcycle.or.kr/main"


def test_detect_location_href_full_url():
    body = '<script>location.href="https://example.com/page";</script>'
    result = detect_js_redirect(body, "https://base.com/")
    assert result == "https://example.com/page"


def test_detect_window_location():
    body = '<script>window.location = "/front/main/main.do";</script>'
    result = detect_js_redirect(body, "https://css.kspo.or.kr/")
    assert result == "https://css.kspo.or.kr/front/main/main.do"


def test_detect_window_location_replace():
    body = '<script>window.location.replace("/new-page");</script>'
    result = detect_js_redirect(body, "https://example.com/")
    assert result == "https://example.com/new-page"


def test_detect_document_location():
    body = '<script>document.location = "/doc-page";</script>'
    result = detect_js_redirect(body, "https://example.com/")
    assert result == "https://example.com/doc-page"


def test_no_redirect_in_normal_html():
    body = '<html><body><h1>Hello</h1></body></html>'
    assert detect_js_redirect(body, "https://example.com/") is None


def test_no_redirect_empty():
    assert detect_js_redirect("", "https://example.com/") is None
