from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kspo_ingest.crawl.board import build_page_url, extract_board_items, is_within_freshness


def test_pagination_stop_when_all_out_of_window():
    now = datetime(2026, 7, 6, tzinfo=UTC)
    old = (now - timedelta(days=200)).strftime("%Y.%m.%d")
    html = (
        f'<table><tr><td>1</td><td><a href="/view.do?nttId=1">a</a></td><td>{old}</td></tr></table>'
    )
    items = extract_board_items(html, base_url="https://x.kr/list.do")
    in_window = [
        it for it in items if is_within_freshness(it.posted_at, freshness_days=90, now=now)
    ]
    assert len(items) == 1
    assert len(in_window) == 0  # → 호출자는 페이지네이션 중단


def test_build_page_url_used_for_pagination():
    assert build_page_url("https://x.kr/list.do", 2).endswith("pageIndex=2")
