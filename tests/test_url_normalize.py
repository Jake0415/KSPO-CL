from __future__ import annotations

from kspo_ingest.crawl.url_normalize import normalize_url


def test_strip_tracking_params():
    url, _ = normalize_url("https://example.com/a?utm_source=x&page=2")
    assert "utm_source" not in url
    assert "page=2" in url


def test_preserve_kspo_board_params():
    url, _ = normalize_url("https://www.kspo.or.kr/bbs/view.do?bbsId=N1&nttId=99")
    assert "bbsId=N1" in url
    assert "nttId=99" in url


def test_query_sorted_alphabetically():
    url, _ = normalize_url("https://example.com/?b=2&a=1")
    assert url.endswith("?a=1&b=2")


def test_fragment_stripped():
    url, _ = normalize_url("https://example.com/page#section")
    assert "#" not in url


def test_default_port_removed_https():
    url, _ = normalize_url("https://example.com:443/")
    assert ":443" not in url


def test_default_port_removed_http():
    url, _ = normalize_url("http://example.com:80/")
    assert ":80" not in url


def test_non_default_port_preserved():
    url, _ = normalize_url("https://example.com:8443/")
    assert "example.com:8443" in url


def test_scheme_and_host_lowercased():
    url, _ = normalize_url("HTTPS://EXAMPLE.COM/Path")
    assert url.startswith("https://example.com/")
    assert "/Path" in url  # path 대소문자는 보존


def test_empty_path_becomes_root():
    url, _ = normalize_url("https://example.com")
    assert url == "https://example.com/"


def test_trailing_slash_preserved():
    a, _ = normalize_url("https://example.com/dir/")
    b, _ = normalize_url("https://example.com/dir")
    assert a.endswith("/dir/")
    assert b.endswith("/dir")
    assert a != b  # 의도적으로 구분 보존


def test_duplicate_slashes_collapsed():
    url, _ = normalize_url("https://example.com//a///b")
    assert "//a" not in url[len("https://example.com"):]
    assert "/a/b" in url


def test_same_url_same_hash():
    _, h1 = normalize_url("https://example.com/a?utm_source=x&b=2")
    _, h2 = normalize_url("HTTPS://EXAMPLE.COM/a?b=2")
    assert h1 == h2


def test_http_https_same_identity_hash():
    """동일 페이지의 http/https 변형은 같은 url_hash → 이중 적재 방지."""
    _, h_http = normalize_url("http://www.kspo.or.kr/kspo/main/main.do")
    _, h_https = normalize_url("https://www.kspo.or.kr/kspo/main/main.do")
    assert h_http == h_https
    # normalized(fetch URL)의 scheme은 원형 유지
    u_http, _ = normalize_url("http://www.kspo.or.kr/kspo/main/main.do")
    u_https, _ = normalize_url("https://www.kspo.or.kr/kspo/main/main.do")
    assert u_http.startswith("http://")
    assert u_https.startswith("https://")


def test_hash_is_40_hex_chars():
    _, h = normalize_url("https://example.com/")
    assert len(h) == 40
    assert all(c in "0123456789abcdef" for c in h)


def test_lone_question_mark_dropped():
    url, _ = normalize_url("https://example.com/a?")
    assert "?" not in url


# --- kspo.or.kr eGov 포털 중복 방지 (view.do 정체성 = bbsId+nttId) ---
def test_kspo_view_same_nttId_dedup_across_menu_page_search():
    """같은 nttId를 다른 menuNo/pageIndex/searchWrd로 접근해도 url_hash 동일."""
    base = "https://www.kspo.or.kr/news/bbs/B0000095/view.do"
    _, h1 = normalize_url(f"{base}?nttId=64052&menuNo=1200001&searchWrd=&pageIndex=4")
    _, h2 = normalize_url(f"{base}?nttId=64052&menuNo=1200001&searchWrd=&pageIndex=1")
    _, h3 = normalize_url(f"{base}?nttId=64052&menuNo=9999999&searchWrd=협약&pageIndex=2")
    assert h1 == h2 == h3


def test_kspo_view_fetch_url_keeps_menuNo():
    """normalized(=fetch URL)는 menuNo를 보존해야 함 (없으면 stub 응답)."""
    base = "https://www.kspo.or.kr/news/bbs/B0000095/view.do"
    url, _ = normalize_url(f"{base}?nttId=64052&menuNo=1200001&pageIndex=4")
    assert "menuNo=1200001" in url
    assert "nttId=64052" in url


def test_kspo_list_pagination_pageIndex_preserved_in_hash():
    """목록(list.do)의 서로 다른 pageIndex는 다른 url_hash여야 페이지네이션 유지."""
    base = "https://www.kspo.or.kr/news/bbs/B0000095/list.do"
    _, h1 = normalize_url(f"{base}?menuNo=1200001&pageIndex=1")
    _, h2 = normalize_url(f"{base}?menuNo=1200001&pageIndex=2")
    assert h1 != h2


def test_kspo_list_menuNo_dropped_from_hash():
    """같은 게시판(bbsId) 목록을 다른 menuNo로 접근하면 같은 정체성."""
    b1 = "https://www.kspo.or.kr/news/bbs/B0000095/list.do?menuNo=1200001&pageIndex=1"
    b2 = "https://www.kspo.or.kr/news/bbs/B0000095/list.do?menuNo=1200002&pageIndex=1"
    _, h1 = normalize_url(b1)
    _, h2 = normalize_url(b2)
    assert h1 == h2


# --- CMS 콘텐츠 페이지(contents.do): menuNo가 유일한 콘텐츠 식별자 ---
def test_kspo_contents_menuNo_is_identity():
    """contents.do?menuNo=X 는 menuNo가 유일한 식별자 → 다른 menuNo는 다른 url_hash.

    Regression: menuNo를 무조건 노이즈로 제거하면 모든 contents.do 가 한 해시로
    붕괴되어 경로당 한 페이지만 저장(찾아오시는길 menuNo=200207 등 누락)된다.
    """
    base = "https://www.kspo.or.kr/kspo/main/contents.do"
    _, h_directions = normalize_url(f"{base}?menuNo=200207")   # 찾아오시는길
    _, h_intro = normalize_url(f"{base}?menuNo=200018")        # 기관소개
    _, h_org = normalize_url(f"{base}?menuNo=200242")
    assert h_directions != h_intro != h_org
    assert h_directions != h_org


def test_kspo_contents_fetch_url_and_hash_keep_menuNo():
    url, _ = normalize_url("https://www.kspo.or.kr/kspo/main/contents.do?menuNo=200207")
    assert "menuNo=200207" in url  # fetch URL preserved as before


def test_kspo_contents_searchWrd_still_noise():
    """contents.do 에서도 searchWrd/searchCnd 는 항상 노이즈."""
    base = "https://www.kspo.or.kr/kspo/main/contents.do?menuNo=200207"
    _, h1 = normalize_url(base)
    _, h2 = normalize_url(base + "&searchWrd=주소&searchCnd=1")
    assert h1 == h2
