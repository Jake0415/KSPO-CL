from __future__ import annotations

from pathlib import Path

import pytest

from kspo_ingest.clean.extractor import MIN_BODY_LEN_FOR_ACCEPT, extract
from kspo_ingest.clean.selectors import load_global_selectors


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "clean"


@pytest.fixture(scope="module")
def selectors() -> list[str]:
    return load_global_selectors()


@pytest.fixture
def board_html() -> bytes:
    return (FIXTURES / "board.html").read_bytes()


@pytest.fixture
def login_html() -> bytes:
    return (FIXTURES / "login.html").read_bytes()


@pytest.fixture
def error_html() -> bytes:
    return (FIXTURES / "error.html").read_bytes()


def test_board_uses_main_article_or_trafilatura(board_html, selectors):
    r = extract(board_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    assert r.method in ("main_article", "trafilatura")
    assert r.title is not None
    assert "2026년 일반사업 공모 공고" in r.title
    assert "공모를" in r.body_text or "공모를" in r.body_text  # 본문 핵심 키워드 추출 확인
    assert len(r.body_text) >= MIN_BODY_LEN_FOR_ACCEPT


def test_board_blacklist_removes_navigation_residue(board_html, selectors):
    r = extract(board_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    # 글로벌 selector로 제거된 영역이 본문에 누설되지 않아야 함
    assert "사이트 공통 헤더" not in r.body_text
    assert "사이트 공통 푸터" not in r.body_text
    assert "관련 공고 모음" not in r.body_text


def test_login_falls_to_heuristic_short(login_html, selectors):
    r = extract(login_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    # 본문이 매우 짧으므로 heuristic 단계 도달 + 길이 < MIN_BODY_LEN_FOR_ACCEPT
    assert r.method == "heuristic"
    assert len(r.body_text) < MIN_BODY_LEN_FOR_ACCEPT


def test_error_falls_to_heuristic_short(error_html, selectors):
    r = extract(error_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    assert r.method == "heuristic"
    assert len(r.body_text) < MIN_BODY_LEN_FOR_ACCEPT
    assert r.title == "404"


def test_raw_html_decoded_present(board_html, selectors):
    r = extract(board_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    assert "<html" in r.raw_html_decoded.lower()


def test_extraction_idempotent(board_html, selectors):
    r1 = extract(board_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    r2 = extract(board_html, content_type="text/html; charset=utf-8", blacklist=selectors)
    assert r1.body_text == r2.body_text
    assert r1.method == r2.method


# --- 데이터 표가 있는 페이지는 trafilatura 우선 -------------------------------
# main_article(node.text)은 표를 셀 단위 세로 나열로 풀어 "항목 ↔ 값" 결합을 잃는다.
# trafilatura(include_tables=True)는 파이프 표로 행/열을 보존한다.

_TABLE_PAGE = """<html><head><title>기금 수입 운용상황</title></head><body>
<main>
<h2>기금 수입 운용상황</h2>
<p>월별 기금 수입 운영 상황을 안내합니다. 아래 표에서 소관명과 회계명, 계정명, 수입관명별
예산현액과 당일수납금액, 당월수납금액, 누계수납금액을 확인하실 수 있습니다. 금액 단위는
원이며, 회계년도와 회계일자 기준으로 집계됩니다. 자세한 사항은 담당 부서로 문의하시기 바랍니다.</p>
<table>
<thead><tr><th>수입관명</th><th>수입항명</th><th>예산현액</th><th>누계수납금액</th></tr></thead>
<tbody>
<tr><td>정부내부수입및기타</td><td>예탁이자수입</td><td>37,665,000,000</td><td>16,462,655,020</td></tr>
<tr><td>재산수입</td><td>기타이자수입및재산수입</td><td>46,501,000,000</td><td>20,561,834,037</td></tr>
<tr><td>수입관1</td><td>수입항목1</td><td>17,665,000,000</td><td>16,462,655,020</td></tr>
<tr><td>수입관2</td><td>수입항목2</td><td>27,665,000,000</td><td>26,462,655,020</td></tr>
<tr><td>수입관3</td><td>수입항목3</td><td>37,665,000,000</td><td>36,462,655,020</td></tr>
<tr><td>수입관4</td><td>수입항목4</td><td>47,665,000,000</td><td>46,462,655,020</td></tr>
<tr><td>수입관5</td><td>수입항목5</td><td>57,665,000,000</td><td>56,462,655,020</td></tr>
<tr><td>수입관6</td><td>수입항목6</td><td>67,665,000,000</td><td>66,462,655,020</td></tr>
</tbody>
</table>
<p>기금 수입 운용상황은 매월 갱신되며, 담당자는 예산팀입니다. 문의는 02-410-1173으로
연락하시면 안내받으실 수 있습니다. 과거 회계년도 자료는 검색 조건에서 연도를 선택해 조회합니다.</p>
</main></body></html>"""


def test_data_table_page_uses_trafilatura(selectors):
    r = extract(_TABLE_PAGE.encode(), content_type="text/html; charset=utf-8", blacklist=selectors)
    assert r.method == "trafilatura"


def test_data_table_keeps_label_and_value_on_same_line(selectors):
    """회귀 방지 — 항목명과 금액이 같은 줄에 남아야 한다."""
    r = extract(_TABLE_PAGE.encode(), content_type="text/html; charset=utf-8", blacklist=selectors)
    lines = r.body_text.split("\n")
    assert any("예탁이자수입" in ln and "16,462,655,020" in ln for ln in lines)
    assert any("재산수입" in ln and "20,561,834,037" in ln for ln in lines)


_NO_TABLE_PAGE = """<html><head><title>사업실명제 개요</title></head><body>
<main>
<h2>사업실명제 개요</h2>
<p>사업실명제는 공공기관이 추진 중인 사업 가운데 국정과제, 재무적 영향이 큰 사업,
대국민 서비스 사업, 현안사안 등 주요사업에 대한 사업내역서를 기관 홈페이지를 통해
대국민에게 공개함으로써 사업 담당자의 책임성을 높이고 투명하게 사업을 추진하기 위한
제도입니다. 대상사업 선정 절차는 심의위원회 구성, 선정기준 확정, 의견 수렴,
대상사업 확정 순으로 진행됩니다.</p>
</main></body></html>"""


def test_page_without_table_still_uses_main_article(selectors):
    """표가 없으면 기존 경로(main_article) 그대로 — 회귀 없음."""
    r = extract(_NO_TABLE_PAGE.encode(), content_type="text/html; charset=utf-8",
                blacklist=selectors)
    assert r.method == "main_article"
    assert "사업 담당자의 책임성" in r.body_text
