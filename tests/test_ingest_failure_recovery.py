from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APITimeoutError
from tenacity import wait_none

from kspo_ingest.attach.discovery import discover_attachments
from kspo_ingest.clean.extractor import extract
from kspo_ingest.crawl.board import _onclick_detail_url, extract_board_items
from kspo_ingest.crawl.external_links import external_access_blocked, external_metadata
from kspo_ingest.crawl.internal_links import discover_internal_links
from kspo_ingest.refine import provider


def test_valueless_meta_and_download_attributes_are_safe():
    html = '<meta content><meta name="description" content><a onclick href="/a.pdf">PDF</a>'
    assert external_access_blocked(html) is False
    assert external_metadata(html) == (None, "")
    assert discover_attachments(html, base_url="https://example.org/")[0].file_name == "a.pdf"


def test_download_handlers_stay_metadata_only():
    html = """<a href="/measureMusicDownLoad.kspo">측정음악</a>
        <a href="/front/dextDownload.down?fileName=report.pdf">보고서</a>
        <a href="/normal">안내</a>"""
    assert len(discover_attachments(html, base_url="https://example.org/")) == 2
    assert discover_internal_links(html, base_url="https://example.org/", host="example.org") == [
        "https://example.org/normal"
    ]


def test_cp949_meta_does_not_reencode_decoded_unicode():
    text = "스포츠산업 실태조사 안내입니다. " * 30
    raw = (
        '<html><head><meta charset="euc-kr"><title>보고서</title></head><body><main>'
        + text
        + "</main></body></html>"
    ).encode("cp949")
    result = extract(raw, "text/html; charset=euc-kr")
    assert "스포츠산업 실태조사" in result.body_text
    assert result.title == "보고서"


@pytest.mark.parametrize(
    "host,path,script,expected",
    [
        (
            "nfa.kspo.or.kr",
            "/community/employ/selectEmployList.kspo",
            """function fnBoardContentView(contSn){
        $("#contSn").val(contSn);
        $("#frm").attr("action", "/community/employ/selectEmployView.kspo");
        $("#frm").submit();
    }""",
            "https://nfa.kspo.or.kr/community/employ/selectEmployView.kspo?contSn=40717",
        ),
        (
            "spobiz.kspo.or.kr",
            "/job/front/job/cs/cs_center/noticeList.do",
            """function fnBoardContentView(seq){
        var strUrl = "/job/front/job/cs/cs_center/noticeDetailView.do";
        strUrl += "?notice_seq=" + seq;
        strUrl += "&board_id=" + $("#board_id").val();
        location.href = strUrl;
    }""",
            "https://spobiz.kspo.or.kr/job/front/job/cs/cs_center/noticeDetailView.do?board_id=10000&notice_seq=40717",
        ),
    ],
)
def test_actual_form_and_query_detail_routes(host, path, script, expected):
    field = (
        '<input type="hidden" id="contSn" name="contSn">'
        if host.startswith("nfa")
        else '<input type="hidden" id="board_id" name="board_id" value="10000">'
    )
    html = (
        "<script>"
        + script
        + "</script>"
        + field
        + """<table><tr><td><a href="#none" onclick="fnBoardContentView('40717')">채용</a></td>
        <td>2026-10-19</td></tr></table>"""
    )
    base = "https://" + host + path
    assert extract_board_items(html, base_url=base)[0].url == expected
    links = discover_internal_links(html, base_url=base, host=host)
    assert expected in links
    assert not any(".do/40717" in link or ".kspo/40717" in link for link in links)


def test_unknown_board_action_does_not_invent_detail_path():
    assert _onclick_detail_url("https://example.org/selectEmployList.kspo", "123") is None


def test_empty_required_ids_are_not_pages():
    html = '<a href="/view.kspo?classSn=">없는 상세</a><a href="/search.do">검색 화면</a>'
    assert discover_internal_links(html, base_url="https://example.org/", host="example.org") == [
        "https://example.org/search.do"
    ]


@pytest.mark.asyncio
async def test_refine_timeout_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(provider.settings, "refine_max_attempts", 2)
    monkeypatch.setattr(provider.settings, "refine_total_timeout_seconds", 1)
    monkeypatch.setattr(provider, "wait_exponential", lambda **kwargs: wait_none())
    create = AsyncMock(
        side_effect=APITimeoutError(request=httpx.Request("POST", "https://example.org"))
    )
    llm = provider.LlmProvider(
        "test",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
        "test",
    )
    with pytest.raises(APITimeoutError):
        await llm.chat_completion(messages=[])
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_refine_total_deadline_cancels_slow_request(monkeypatch):
    monkeypatch.setattr(provider.settings, "refine_total_timeout_seconds", 0.02)
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    llm = provider.LlmProvider(
        "test",
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=slow))),
        "test",
    )
    with pytest.raises(TimeoutError):
        await llm.chat_completion(messages=[])
    assert cancelled.is_set()


def test_provider_disables_sdk_retry_multiplication():
    provider.reset_providers()
    assert provider.get_provider("openai").client.max_retries == 0
    provider.reset_providers()


@pytest.mark.asyncio
async def test_dynamic_keeps_source_when_navigation_changes(monkeypatch):
    from kspo_ingest.crawl import dynamic

    waiter = SimpleNamespace(start=lambda: None)
    waiter.wait = AsyncMock(return_value={"ready": True})
    waiter.snapshot = AsyncMock(return_value={"url": "https://example.org/list", "document_id": 1})
    waiter.close = lambda: None
    waiter.start = lambda: waiter
    monkeypatch.setattr(dynamic, "ContentWaiter", lambda *args: waiter)
    source = "<html><body><main>Existing public content</main></body></html>"
    page = SimpleNamespace(
        url="https://example.org/list",
        content=AsyncMock(side_effect=[source, RuntimeError("navigating")]),
        route=AsyncMock(),
        unroute=AsyncMock(),
        on=lambda *args: None,
        remove_listener=lambda *args: None,
    )
    initial = SimpleNamespace(
        url="https://example.org/api",
        status=200,
        headers={"content-type": "application/json"},
        request=SimpleNamespace(resource_type="xhr"),
        body=AsyncMock(return_value=b'{"title":"initial AJAX"}'),
    )
    page.reload = AsyncMock(side_effect=AssertionError("unnecessary reload"))
    html, report = await dynamic.expand_readonly(page, initial_responses=[initial])
    assert "<main>" in html and "initial AJAX" in html
    assert report["stop_reason"] == "navigation_in_progress"
    page.reload.assert_not_awaited()


def test_binary_downloads_never_enter_html_extraction():
    from kspo_ingest.attach.discovery import is_binary_content

    assert is_binary_content(b"%PDF-1.7 binary data", "application/x-msdownload;charset=UTF-8")
    assert is_binary_content(b"PK\x03\x04binary", "application/octet-stream")
    assert not is_binary_content(b"<html>Content</html>", "application/octet-stream")
    assert not is_binary_content(b"<html>Content</html>", "text/html")
