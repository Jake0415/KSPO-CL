"""coverage._article_id — 목록/상세 경로 형태가 달라도 같은 글을 매칭하는지."""
from __future__ import annotations

from kspo_ingest.quality.coverage import _article_id


def test_path_id_matches_across_list_and_detail_shapes():
    """soma류: 목록형 /class/04/list/430 과 실제 상세 /class/430 이 같은 ID."""
    assert _article_id("https://soma.kspo.or.kr/class/04/list/430") == "p:430"
    assert _article_id("https://soma.kspo.or.kr/class/430") == "p:430"
    assert (
        _article_id("https://www.kospole.co.kr/toto/board/bidding/4275")
        == _article_id("https://www.kospole.co.kr/toto/board/detail/4275")
    )


def test_query_param_id_priority():
    """전자정부 표준: conSeq/nttId 등 파라미터ID를 우선 사용."""
    assert _article_id(
        "https://www.spoinfo.or.kr/board/bs/boardView.do?boardSeq=1&conSeq=5852"
    ) == "conseq:5852"
    assert _article_id("https://x/view.do?nttId=64209") == "nttid:64209"


def test_no_id_for_bare_list():
    """식별 숫자가 없는 목록 페이지는 ID 없음(2자리 이하 세그먼트 무시)."""
    assert _article_id("https://soma.kspo.or.kr/class/04/list") is None
    assert _article_id("https://www.kospole.co.kr/toto/board/bidding") is None


def test_param_and_path_namespaces_do_not_collide():
    """파라미터ID(conseq:5852)와 경로ID(p:5852)는 서로 매칭되지 않는다."""
    assert _article_id("https://x/v.do?conSeq=5852") != _article_id("https://x/a/5852")
