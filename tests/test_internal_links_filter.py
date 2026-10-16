from __future__ import annotations

from kspo_ingest.crawl.internal_links import discover_internal_links

HTML_WITH_LOGIN_DUPES = """
<html><body>
<a href="/main.do">메인</a>
<a href="/contents.do?menuNo=1">안내</a>
<a href="/login/login.do?menuNo=43&topMenuNo=42">로그인1</a>
<a href="/login/login.do?menuNo=800043&topMenuNo=800042">로그인2</a>
<a href="/login/login.do?menuNo=99">로그인3</a>
<a href="/mypage/goMypage.do">마이페이지</a>
<a href="/member/memberJoinSelect.do">회원가입</a>
<a href="/login/findMemberInfo.do">아이디찾기</a>
<a href="/bbs/list.do?menuNo=100">공지사항</a>
<a href="/bbs/list.do?menuNo=200">다른메뉴의 공지사항</a>
</body></html>
"""


def test_login_pages_excluded():
    links = discover_internal_links(
        HTML_WITH_LOGIN_DUPES, base_url="https://example.kspo.or.kr/", host="example.kspo.or.kr"
    )
    urls_str = " ".join(links)
    assert "/login/" not in urls_str
    assert "/mypage/" not in urls_str
    assert "memberJoinSelect" not in urls_str
    assert "/findMemberInfo" not in urls_str


def test_menu_param_dedup():
    links = discover_internal_links(
        HTML_WITH_LOGIN_DUPES, base_url="https://example.kspo.or.kr/", host="example.kspo.or.kr"
    )
    bbs_links = [l for l in links if "/bbs/list.do" in l]
    assert len(bbs_links) == 1  # menuNo=100과 200은 같은 path → 1개만


def test_valid_pages_kept():
    links = discover_internal_links(
        HTML_WITH_LOGIN_DUPES, base_url="https://example.kspo.or.kr/", host="example.kspo.or.kr"
    )
    paths = [l.split("kspo.or.kr")[1] for l in links]
    assert any("/main.do" in p for p in paths)
    assert any("/contents.do" in p for p in paths)
    assert any("/bbs/list.do" in p for p in paths)


def test_total_count():
    links = discover_internal_links(
        HTML_WITH_LOGIN_DUPES, base_url="https://example.kspo.or.kr/", host="example.kspo.or.kr"
    )
    # main.do + contents.do + bbs/list.do = 3개 (로그인4개+마이페이지+회원가입+아이디찾기 제외, bbs 중복 제거)
    assert len(links) == 3


# === onclick goView 게시판 상세 링크 발견 ===

HTML_BOARD_LIST = """
<html><body>
<a href="/bbs/B0000078/list.do?menuNo=800018">공지사항</a>
<a href="#" onclick="javascript:goView('63978');return false;">결제 오류 안내</a>
<a href="#" onclick="javascript:goView('63621');return false;">현장모니터링</a>
<a href="#" onclick="javascript:goView('63562');return false;">신청안내</a>
<a href="#" onclick="javascript:goView('63562');return false;">중복 글</a>
</body></html>
"""


def test_board_goview_discovered():
    """onclick goView → view.do?nttId=ID URL이 발견되어야 함."""
    links = discover_internal_links(
        HTML_BOARD_LIST,
        base_url="https://dvoucher.kspo.or.kr/dvoucher/bbs/B0000078/list.do?menuNo=800018",
        host="dvoucher.kspo.or.kr",
    )
    view_links = [l for l in links if "view.do" in l and "nttId" in l]
    assert len(view_links) == 3  # 63978, 63621, 63562 (중복 제거)
    assert any("nttId=63978" in l for l in view_links)
    assert any("nttId=63621" in l for l in view_links)


def test_board_goview_not_on_non_list_page():
    """list.do가 아닌 페이지에서는 goView 변환 안 함."""
    links = discover_internal_links(
        HTML_BOARD_LIST,
        base_url="https://dvoucher.kspo.or.kr/main.do",
        host="dvoucher.kspo.or.kr",
    )
    view_links = [l for l in links if "view.do" in l]
    assert len(view_links) == 0


HTML_BOARD_FN_VIEW = """
<html><body>
<a href="#" onclick="fnBoardContentView('39972')">파트너스 모집</a>
<a href="#" onclick="fnBoardContentView('39905')">예약 안내</a>
</body></html>
"""


def test_board_fnview_discovered():
    """onclick fnBoardContentView → view URL 발견."""
    links = discover_internal_links(
        HTML_BOARD_FN_VIEW,
        base_url="https://example.com/bbs/list.do?menuNo=1",
        host="example.com",
    )
    view_links = [l for l in links if "View.do" in l or "view.do" in l]
    assert len(view_links) == 2


# === 게시판 페이지네이션 ===

HTML_BOARD_WITH_PAGINATION = """
<html><body>
<a href="#" onclick="goPage('1')">1</a>
<a href="#" onclick="goPage('2')">2</a>
<a href="#" onclick="goPage('3')">3</a>
<a href="#" onclick="goPage('4')">4</a>
<a href="#" onclick="goPage('5')">5</a>
<a href="#" onclick="goView('100')">글1</a>
<a href="#" onclick="goView('101')">글2</a>
</body></html>
"""


def test_pagination_links_generated():
    """게시판 목록에서 pageNo=2~5 링크가 생성되어야 함."""
    links = discover_internal_links(
        HTML_BOARD_WITH_PAGINATION,
        base_url="https://dvoucher.kspo.or.kr/dvoucher/bbs/B0000078/list.do?menuNo=800018",
        host="dvoucher.kspo.or.kr",
    )
    page_links = [l for l in links if "pageNo=" in l]
    assert len(page_links) == 4  # pageNo=2,3,4,5
    assert any("pageNo=2" in l for l in page_links)
    assert any("pageNo=5" in l for l in page_links)


def test_pagination_not_on_non_list():
    """list 페이지가 아닌 곳에서는 pagination 미생성."""
    links = discover_internal_links(
        HTML_BOARD_WITH_PAGINATION,
        base_url="https://example.com/main.do",
        host="example.com",
    )
    page_links = [l for l in links if "pageNo=" in l]
    assert len(page_links) == 0


HTML_BOARD_HREF_PAGINATION = """
<html><body>
<a href="/board/list.do?boardSeq=6&pageNo=1">1</a>
<a href="/board/list.do?boardSeq=6&pageNo=2">2</a>
<a href="/board/list.do?boardSeq=6&pageNo=27">마지막</a>
</body></html>
"""


def test_pagination_from_href():
    """href pageNo 패턴에서 최대 페이지까지 생성."""
    links = discover_internal_links(
        HTML_BOARD_HREF_PAGINATION,
        base_url="https://www.spoinfo.or.kr/board/bs/boardList.do?boardSeq=6&menuSeq=10054",
        host="www.spoinfo.or.kr",
    )
    page_links = [l for l in links if "pageNo=" in l]
    # href 3개 + pagination 생성 26개 (중복 path 차이로 합산)
    assert len(page_links) >= 26
    assert any("pageNo=27" in l for l in page_links)


# --- KSPO pageIndex 페이지네이션 (전자정부프레임워크) — Bug A/B 회귀 방지 ---
HTML_BOARD_PAGEINDEX = """
<html><body>
<a href="/kspo/bbs/B0000006/list.do?menuNo=200028&pageIndex=1">1</a>
<a href="/kspo/bbs/B0000006/list.do?menuNo=200028&pageIndex=2">2</a>
<a href="/kspo/bbs/B0000006/list.do?menuNo=200028&pageIndex=3">3</a>
<a href="/kspo/bbs/B0000006/list.do?menuNo=200028&pageIndex=8">8</a>
<a href="/kspo/bbs/B0000006/view.do?menuNo=200028&nttId=100&pageIndex=1">글1</a>
<a href="/kspo/bbs/B0000006/view.do?menuNo=200028&nttId=101&pageIndex=1">글2</a>
</body></html>
"""


def test_pageindex_pagination_survives_dedup():
    """Bug A: href pageIndex=2,3,8 목록 링크가 dedup에서 살아남아야 함."""
    links = discover_internal_links(
        HTML_BOARD_PAGEINDEX,
        base_url="https://www.kspo.or.kr/kspo/bbs/B0000006/list.do?menuNo=200028",
        host="www.kspo.or.kr",
    )
    list_pages = [u for u in links if "list.do" in u and "pageIndex=" in u]
    assert any("pageIndex=2" in u for u in list_pages)
    assert any("pageIndex=3" in u for u in list_pages)
    assert any("pageIndex=8" in u for u in list_pages)


def test_pageindex_pagination_generated_to_max():
    """Bug B: _add_pagination_links가 pageIndex=2~max(8) 전부 생성 (창에 없는 4~7 포함)."""
    links = discover_internal_links(
        HTML_BOARD_PAGEINDEX,
        base_url="https://www.kspo.or.kr/kspo/bbs/B0000006/list.do?menuNo=200028",
        host="www.kspo.or.kr",
    )
    page_links = [u for u in links if "pageIndex=" in u and "list.do" in u]
    for n in (2, 4, 7, 8):
        assert any(f"pageIndex={n}" in u for u in page_links), f"pageIndex={n} 누락"
    assert not any("pageNo=" in u for u in page_links)  # KSPO는 pageIndex


def test_view_pageindex_still_deduped():
    """회귀 방지: view.do는 nttId로 식별 — pageIndex가 달라도 같은 글이면 1개."""
    html = (
        '<a href="/bbs/view.do?nttId=100&pageIndex=1">a</a>'
        '<a href="/bbs/view.do?nttId=100&pageIndex=2">b</a>'
    )
    links = discover_internal_links(
        html, base_url="https://x.kspo.or.kr/bbs/list.do", host="x.kspo.or.kr"
    )
    assert len([u for u in links if "view.do" in u]) == 1
