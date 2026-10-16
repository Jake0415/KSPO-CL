from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kspo_ingest.crawl.board import (
    _parse_date,
    classify_freshness,
    extract_board_items,
    is_within_freshness,
)

SAMPLE_BOARD_HTML = """
<html><body>
<table class="board-list">
<tr>
  <td class="title"><a href="/bbs/view.do?id=123">공지사항 제목 1</a></td>
  <td class="date">2026-07-01</td>
</tr>
<tr>
  <td class="title"><a href="/bbs/view.do?id=122">공지사항 제목 2</a></td>
  <td class="date">2026-03-15</td>
</tr>
<tr>
  <td class="title"><a href="/bbs/view.do?id=100">오래된 글</a></td>
  <td class="date">2025-12-01</td>
</tr>
</table>
</body></html>
"""


def test_extract_board_items():
    items = extract_board_items(SAMPLE_BOARD_HTML, base_url="https://www.kspo.or.kr")
    assert len(items) == 3
    assert items[0].url == "https://www.kspo.or.kr/bbs/view.do?id=123"
    assert items[0].posted_at.year == 2026
    assert items[0].posted_at.month == 7


def test_freshness_filter_recent():
    now = datetime(2026, 7, 4, tzinfo=UTC)
    assert is_within_freshness(
        datetime(2026, 7, 1, tzinfo=UTC), freshness_days=90, now=now
    )


def test_freshness_filter_old():
    now = datetime(2026, 7, 4, tzinfo=UTC)
    assert not is_within_freshness(
        datetime(2025, 12, 1, tzinfo=UTC), freshness_days=90, now=now
    )


def test_freshness_filter_boundary():
    now = datetime(2026, 7, 4, tzinfo=UTC)
    assert is_within_freshness(
        datetime(2026, 4, 5, tzinfo=UTC), freshness_days=90, now=now
    )
    assert not is_within_freshness(
        datetime(2026, 4, 4, tzinfo=UTC), freshness_days=90, now=now
    )


def test_extract_empty_html():
    items = extract_board_items("", base_url="https://www.kspo.or.kr")
    assert items == []


# ---------------------------------------------------------------------------
# Task 2: 공지행 스킵 · classify_board_list · build_page_url
# ---------------------------------------------------------------------------
from kspo_ingest.crawl.board import (  # noqa: E402
    BoardSignal,
    build_page_url,
    classify_board_list,
)

_LIST_HTML = """
<table><thead><tr><th>게시일</th></tr></thead>
 <tr class="notice"><td>공지</td><td><a href="/view.do?nttId=1">중요</a></td>
 <td>2020.01.01</td></tr>
 <tr><td>10</td><td><a href="/view.do?nttId=10">글A</a></td><td>2026.07.01</td></tr>
 <tr><td>9</td><td><a href="/view.do?nttId=9">글B</a></td><td>2026.06.20</td></tr>
</table>
<div class="paging"><a href="?pageNo=2">2</a><a href="?pageIndex=3">3</a></div>
"""


def test_extract_board_items_includes_dated_notice_row():
    items = extract_board_items(_LIST_HTML, base_url="https://x.kr/list.do")
    urls = [it.url for it in items]
    assert "https://x.kr/view.do?nttId=1" in urls  # 날짜가 있는 고정 공지도 포함
    assert "https://x.kr/view.do?nttId=10" in urls
    assert len(items) == 3


def test_classify_board_list_two_signals_true():
    sig = classify_board_list(_LIST_HTML, base_url="https://x.kr/bbs/list.do")
    assert isinstance(sig, BoardSignal)
    assert sig.has_pagination is True
    assert sig.dated_rows >= 2
    assert sig.is_board is True


def test_classify_non_board_single_signal_false():
    html = "<table><tr><td>x</td></tr></table>"
    sig = classify_board_list(html, base_url="https://x.kr/about")
    assert sig.is_board is False


def test_build_page_url_appends_pageno():
    assert build_page_url("https://x.kr/list.do", 3) == "https://x.kr/list.do?pageIndex=3"
    assert (
        build_page_url("https://x.kr/list.do?menuNo=5", 2)
        == "https://x.kr/list.do?menuNo=5&pageIndex=2"
    )
    assert build_page_url("https://x.kr/list.do?pageNo=1", 4) == "https://x.kr/list.do?pageNo=4"


def test_classify_freshness_ok():
    now = datetime(2026, 8, 4, tzinfo=UTC)
    assert classify_freshness(now - timedelta(days=10), now=now) == "ok"


def test_classify_freshness_stale():
    now = datetime(2026, 8, 4, tzinfo=UTC)
    assert classify_freshness(now - timedelta(days=120), now=now) == "stale"


def test_classify_freshness_no_date():
    assert classify_freshness(None) == "no_date"


def test_board_parse_korean_date():
    dt = _parse_date("자유글 2026년 8월 4일 조회 3")
    assert dt is not None and dt.month == 8 and dt.day == 4
