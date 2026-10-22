import pytest

from kspo_ingest.crawl.board import empty_board_reason, extract_board_items

BASE = "https://www.kcycle.or.kr/clinic/achive/cardnews?pagination.currentPage=2"


@pytest.mark.parametrize(
    "controls",
    [
        '<li><a href="javascript:void(0)" onclick="fnSearch(1)">1</a></li>',
        '<li><a onclick="fnToggleIntgSearch()">통합검색</a></li>',
        '<li><a onclick="fnPopupActivePointGuide()">활동지수</a></li>',
        '<li><a onclick="fnPage(2)">다음</a></li>',
        '<div class="pagination"><a onclick="go(2)">다음</a></div>',
    ],
)
def test_empty_page_with_global_controls_is_normal_end(controls):
    html = f'<main><div class="no-data">게시물이 없습니다</div>{controls}</main>'
    assert extract_board_items(html, base_url=BASE) == []
    assert empty_board_reason(html, base_url=BASE) == "empty_list"


def test_global_navigation_details_do_not_mark_empty_board_as_failure():
    html = '<header><a href="/view.do?nttId=1">안내</a></header><main>게시물이 없습니다</main>'
    assert empty_board_reason(html, base_url=BASE) == "empty_list"


@pytest.mark.parametrize(
    "link",
    [
        '<a href="/view.do?nttId=1">날짜가 누락된 글</a>',
        '<a href="/clinic/achive/cardnews/123">날짜가 누락된 카드</a>',
        '<a href="javascript:void(0)" onclick="fnMoveDetail(123)">글</a>',
    ],
)
def test_actual_article_without_date_keeps_partial_warning(link):
    html = f"<main><ul><li>{link}</li></ul></main>"
    assert extract_board_items(html, base_url=BASE) == []
    assert empty_board_reason(html, base_url=BASE) == "unparsed_list"


def test_valid_image_card_still_extracts_link_and_date():
    html = (
        '<main><ul><li><a href="/clinic/achive/cardnews/123">'
        '<img src="/image.png" alt="카드뉴스"></a>'
        "<time>2026.10.20</time></li></ul></main>"
    )
    items = extract_board_items(html, base_url=BASE)
    assert len(items) == 1 and items[0].url.endswith("/123")
