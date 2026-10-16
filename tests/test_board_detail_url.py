"""board._onclick_detail_url — 목록형 URL을 실제 상세 URL로 올바르게 변환하는지."""
from __future__ import annotations

from kspo_ingest.crawl.board import _onclick_detail_url as build


def test_kspo_egov_list_do_to_view_nttid():
    """KSPO 표준 eGov: list.do → view.do?nttId (svoucher/dvoucher goView 목록)."""
    assert build("https://svoucher.kspo.or.kr/svoucher/bbs/B0000051/list.do?menuNo=20", "64174") == \
        "https://svoucher.kspo.or.kr/svoucher/bbs/B0000051/view.do?nttId=64174"


def test_path_list_with_numeric_category():
    """soma: /class/03/list → /class/{id} (말단 list + 숫자 카테고리 제거)."""
    assert build("https://soma.kspo.or.kr/class/03/list", "444") == "https://soma.kspo.or.kr/class/444"


def test_path_list_without_numeric_category():
    """soma: /draw/notice/list → /draw/notice/{id} (말단 list만 제거)."""
    assert build("https://soma.kspo.or.kr/draw/notice/list", "597") == \
        "https://soma.kspo.or.kr/draw/notice/597"


def test_regression_boardlist_do_conseq():
    """회귀: boardList.do는 기존대로 boardView.do?conSeq (sports/spoinfo)."""
    assert build("https://www.spoinfo.or.kr/board/bs/boardList.do?boardSeq=1", "5852") == \
        "https://www.spoinfo.or.kr/board/bs/boardView.do?boardSeq=1&conSeq=5852"


def test_regression_pathform_family_site():
    """회귀: kboat/kcycle 경로형은 목록 경로에 /{id} 부착."""
    assert build("https://www.kboat.or.kr/customerplaza/notice", "12345") == \
        "https://www.kboat.or.kr/customerplaza/notice/12345"
