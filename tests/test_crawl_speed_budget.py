import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.attach.discovery import discover_attachments, is_attachment_url
from kspo_ingest.crawl import dynamic
from kspo_ingest.crawl.board import extract_board_items
from kspo_ingest.crawl.internal_links import discover_internal_links
from tests.test_dynamic_crawl import FakePage, response


@pytest.mark.asyncio
async def test_time_budget_preserves_html_ajax_and_marks_incomplete(monkeypatch):
    waiter = SimpleNamespace(
        snapshot=AsyncMock(return_value={"url": "https://example.org/list", "document_id": 1}),
        wait=AsyncMock(),
        close=lambda: None,
    )
    waiter.start = lambda: waiter
    monkeypatch.setattr(dynamic, "ContentWaiter", lambda *a: waiter)
    page = FakePage()

    async def slow_click(**kwargs):
        await asyncio.Event().wait()

    page.click = slow_click
    html, report = await dynamic.expand_readonly(
        page, max_elapsed_seconds=0.02, initial_responses=[response(b'{"title":"captured AJAX"}')]
    )
    assert "<main>" in html and "captured AJAX" in html
    assert report["stop_reason"] == "dynamic_time_limit"
    assert report["limit_reached"] and report["needs_review"]


def test_pyxis_files_are_metadata_only_and_not_crawl_pages():
    url = "https://www.sports.re.kr/pyxis-api/1/digital-files/abc-123"
    assert is_attachment_url(url)
    html = f'<a href="{url}">연구 보고서</a><a href="/front/info/list.do">목록</a>'
    assert discover_internal_links(
        html, base_url="https://www.sports.re.kr/", host="www.sports.re.kr"
    ) == ["https://www.sports.re.kr/front/info/list.do"]
    files = discover_attachments(html, base_url="https://www.sports.re.kr/")
    assert len(files) == 1 and files[0].source_url == url
    assert not is_attachment_url("https://www.sports.re.kr/pyxis-api/1/search")


def test_null_notice_image_alt_does_not_break_board_detection():
    html = '<table><tr><td><img alt></td><td><a href="/view.do?nttId=1">안내</a></td><td>2026-10-21</td></tr></table>'
    assert len(extract_board_items(html, base_url="https://example.org/list.do")) == 1
