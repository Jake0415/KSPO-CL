from kspo_ingest.crawl.internal_links import discover_internal_links
from kspo_ingest.crawl.loop_guard import list_family, list_signature
from kspo_ingest.crawl.url_normalize import normalize_url


def test_list_cursor_and_filters():
    a = "https://soma.kspo.or.kr/dspy/display/2024/list?page=1"
    b = "https://soma.kspo.or.kr/dspy/display/2024/list?page=2"
    detail = ["https://soma.kspo.or.kr/dspy/display/209"]
    assert list_signature(a, detail) == list_signature(b, detail)
    assert list_family(a) != list_family(a + "&category=other")
    assert list_signature(a, []) is None


def test_details_ignore_only_navigation():
    u = "https://soma.kspo.or.kr/dspy/display/209"
    assert normalize_url(u)[1] == normalize_url(u + "?form_page_index=5&_form_id=form")[1]
    assert normalize_url(u)[1] != normalize_url(u + "?lang=en")[1]
    assert normalize_url(u)[1] != normalize_url(u.replace("209", "211"))[1]


def test_actual_pagination_only():
    base = "https://example.org/bbs/list.do"
    links = discover_internal_links(
        '<a href="?pageIndex=20">마지막</a>', base_url=base, host="example.org"
    )
    assert links == [base + "?pageIndex=20"]
    links = discover_internal_links(
        "<a onclick=\"goPage('10')\">다음</a>", base_url=base, host="example.org"
    )
    assert links == [base + "?pageNo=10"]


def test_non_list_and_unrelated_menu_are_not_signatures():
    assert list_signature("https://x.com/detail/1", ["https://x.com/detail/2"]) is None
    assert list_signature("https://x.com/list", ["https://x.com/about"]) is None
    assert list_signature("https://x.com/news/list", ["https://x.com/news/123"])
