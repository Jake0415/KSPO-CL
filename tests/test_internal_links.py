"""crawl/internal_links.py 단위 테스트."""

from __future__ import annotations

from kspo_ingest.crawl.internal_links import discover_internal_links


def test_same_host_links_kept():
    html = """
    <a href="/page1">page1</a>
    <a href="/section/page2.html">page2</a>
    <a href="https://example.com/abs">abs</a>
    """
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert "https://example.com/page1" in urls
    assert "https://example.com/section/page2.html" in urls
    assert "https://example.com/abs" in urls
    assert len(urls) == 3


def test_external_host_filtered():
    html = '<a href="https://other.com/">other</a><a href="/local">local</a>'
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert urls == ["https://example.com/local"]


def test_attachment_extensions_skipped():
    html = """
    <a href="/file.pdf">pdf</a>
    <a href="/sheet.xlsx">xlsx</a>
    <a href="/page">page</a>
    """
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert urls == ["https://example.com/page"]


def test_image_media_skipped():
    html = """
    <a href="/img.jpg">jpg</a>
    <a href="/movie.mp4">mp4</a>
    <a href="/icon.svg">svg</a>
    <a href="/article">article</a>
    """
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert urls == ["https://example.com/article"]


def test_javascript_mailto_anchor_excluded():
    html = """
    <a href="javascript:void(0)">js</a>
    <a href="mailto:a@b.com">mail</a>
    <a href="tel:+82-2-123">tel</a>
    <a href="#top">anchor</a>
    <a href="/real">real</a>
    """
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert urls == ["https://example.com/real"]


def test_duplicate_urls_deduped():
    html = '<a href="/x">a</a><a href="/x">b</a><a href="/x?utm=1">c</a>'
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    # path 기준 중복 제거 — /x와 /x?utm=1은 같은 path이므로 1개만 반환
    assert "https://example.com/x" in urls
    assert len(urls) == 1


def test_max_links_truncates():
    links = "".join(f'<a href="/p{i}">p{i}</a>' for i in range(300))
    urls = discover_internal_links(
        links, base_url="https://example.com/", host="example.com", max_links=50
    )
    assert len(urls) == 50


def test_empty_html_returns_empty():
    assert discover_internal_links("", base_url="https://example.com/", host="example.com") == []


def test_host_case_insensitive():
    html = '<a href="https://EXAMPLE.com/up">up</a>'
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert urls == ["https://EXAMPLE.com/up"]


def test_relative_url_resolved_against_base():
    html = '<a href="../sibling">sib</a>'
    urls = discover_internal_links(
        html, base_url="https://example.com/dir/page", host="example.com"
    )
    assert urls == ["https://example.com/sibling"]


# --- contents.do: menuNo가 유일한 식별자이므로 서로 다른 menuNo 링크는 보존 ---
def test_discover_keeps_distinct_contents_menu_no_links():
    """한 페이지가 여러 contents.do?menuNo=X 를 링크하면 모두 발견되어야 한다.

    Regression: menuNo를 dedup 키에서 무조건 제외하면 contents.do 전부가 한 키로
    붕괴되어 페이지당 한 개만 발견된다(찾아오시는길 등 discovery 누락).
    """
    html = """
    <a href="/kspo/main/contents.do?menuNo=200207">찾아오시는길</a>
    <a href="/kspo/main/contents.do?menuNo=200018">기관소개</a>
    <a href="/kspo/main/contents.do?menuNo=200242">조직</a>
    """
    links = discover_internal_links(html, base_url="https://www.kspo.or.kr/", host="www.kspo.or.kr")
    menus = {u.split("menuNo=")[-1] for u in links if "contents.do" in u}
    assert {"200207", "200018", "200242"} <= menus


def test_discover_dedups_board_view_across_menu_no():
    """게시글(view.do, nttId 존재)은 menuNo가 달라도 같은 글 → 하나만 발견."""
    html = """
    <a href="/news/bbs/B1/view.do?nttId=99&menuNo=1">글 A</a>
    <a href="/news/bbs/B1/view.do?nttId=99&menuNo=2">글 A(다른 메뉴)</a>
    """
    links = discover_internal_links(html, base_url="https://www.kspo.or.kr/", host="www.kspo.or.kr")
    view_links = [u for u in links if "view.do" in u]
    assert len(view_links) == 1


def test_discover_js_nav_path_literals():
    """메뉴가 href가 아니라 onclick fnPageMove('/path.kspo') 형태여도 발견한다(sqms류)."""
    html = """
    <li onclick="fnPageMove('/info/schedPlan.kspo','sched','일정','Y')">시험일정</li>
    <li onclick="fnPageMove('/exam/wrQnaList.kspo')">필기Q&A</li>
    <a href="#" onclick="location.href='/support/faqList.kspo?type=1'">FAQ</a>
    <button data-url="/guide/location.kspo">오시는길</button>
    """
    links = discover_internal_links(
        html, base_url="https://sqms.kspo.or.kr/main/main.kspo", host="sqms.kspo.or.kr"
    )
    paths = {u.split("sqms.kspo.or.kr")[-1].split("?")[0] for u in links}
    assert "/info/schedPlan.kspo" in paths
    assert "/exam/wrQnaList.kspo" in paths
    assert "/support/faqList.kspo" in paths
    assert "/guide/location.kspo" in paths


def test_js_nav_ignores_static_assets_and_external():
    """정적 자원(.css/.js)·외부 호스트는 JS 리터럴이어도 추가하지 않는다."""
    html = """
    <li onclick="fnPageMove('/common/css/main.css')">x</li>
    <li onclick="location.href='https://other.com/a.do'">y</li>
    <li onclick="fnPageMove('/info/noticeList.kspo')">공지</li>
    """
    links = discover_internal_links(
        html, base_url="https://sqms.kspo.or.kr/main/main.kspo", host="sqms.kspo.or.kr"
    )
    assert any("noticeList.kspo" in u for u in links)
    assert not any(".css" in u for u in links)
    assert not any("other.com" in u for u in links)


def test_cursor_and_filter_queries_are_not_collapsed():
    html = (
        '<a href="/list?cursor=a&zone=red">A</a>'
        '<a href="/list?cursor=b&zone=red">B</a>'
        '<a href="/list?cursor=a&zone=blue">C</a>'
        '<a href="/list?zone=red&cursor=a&utm_source=test">Duplicate A</a>'
    )
    urls = discover_internal_links(html, base_url="https://example.com/", host="example.com")
    assert len(urls) == 3
