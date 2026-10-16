import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from kspo_ingest.crawl.dynamic import (
    ajax_text,
    expand_readonly,
    has_dynamic_controls,
    interaction_candidates,
    navigation_depth,
    snapshot_content,
)
from kspo_ingest.crawl.soma import discover_urls


@pytest.fixture(autouse=True)
def isolate_readiness():
    with patch("kspo_ingest.crawl.dynamic.ContentWaiter") as cls:
        waiter = cls.return_value.start.return_value
        waiter.wait = AsyncMock(return_value={"mode": "dynamic", "ready": True})
        waiter.snapshot = AsyncMock(
            return_value={"url": "https://example.org/list", "document_id": 1}
        )
        yield waiter


class DynamicRulesTest(unittest.TestCase):
    def test_read_only_controls(self):
        html = (
            "<button>더보기</button><button>삭제 더보기</button>"
            '<button type="submit">조회</button><button aria-expanded="false">항목</button>'
            '<button role="tab">전시</button><button aria-expanded="true">확장</button>'
            '<button role="tab" aria-selected="true">선택</button>'
        )
        self.assertEqual(len(interaction_candidates(html)), 3)
        self.assertTrue(has_dynamic_controls(html))
        self.assertFalse(has_dynamic_controls("<button>저장</button>"))
        self.assertIn(
            "https://soma.kspo.or.kr/piece/product/179",
            discover_urls(
                '<button onclick="fnSclptrView(179)">상세</button>', "https://soma.kspo.or.kr/main"
            ),
        )

    def test_dropdown_choices(self):
        html = (
            '<select name="zone"><option value="a" selected>A</option>'
            '<option value="b">B</option><option value="c">C</option></select>'
        )
        candidates = interaction_candidates(html)
        self.assertEqual([c["option"] for c in candidates], ["b", "c"])

    def test_depth_and_ajax(self):
        base = "https://example.org/list?page=1"
        self.assertEqual(navigation_depth(base, base.replace("1", "2"), 10), 10)
        self.assertEqual(navigation_depth(base, "https://example.org/detail/1", 10), 11)
        self.assertEqual(navigation_depth(base, "https://other.org/list?page=2", 10), 11)
        self.assertEqual(navigation_depth(base, "https://example.org/list?category=a", 10), 11)
        text = ajax_text(
            {"data": [{"title": "작품"}, "<body>내용</body>"], "token": "secret", "count": 5}
        )
        self.assertIn("작품", text)
        self.assertNotIn("secret", text)
        self.assertEqual(ajax_text(5), "")
        self.assertIn(
            "/detail/1",
            snapshot_content('<main><nav>잡음</nav>작품<a href="/detail/1">상세</a></main>'),
        )
        self.assertNotIn("잡음", snapshot_content("<main><nav>잡음</nav>본문</main>"))
        self.assertEqual(snapshot_content(""), "")


class FakePage:
    def __init__(self, *, mode="expand", ajax=None):
        self.url = "https://example.org/list"
        self.state = 0
        self.mode = mode
        self.ajax = ajax or []
        self.blocked = []

    async def content(self):
        extra = '<p>추가 작품 정보</p><a href="/detail/1">작품</a>' if self.state else ""
        return "<html><body><main><button>더보기</button>" + extra + "</main></body></html>"

    async def route(self, pattern, guard):
        for method, url in [
            ("POST", "https://example.org/save"),
            ("POST", "https://example.org/list"),
            ("GET", "https://example.org/main"),
        ]:
            route = SimpleNamespace(
                request=SimpleNamespace(method=method, url=url),
                abort=AsyncMock(),
                continue_=AsyncMock(),
            )
            await guard(route)
            self.blocked.append(route.abort.await_count)

    async def unroute(self, *args):
        pass

    def on(self, name, handler):
        self.handler = handler

    def remove_listener(self, *args):
        pass

    async def reload(self, **kwargs):
        for response in self.ajax:
            self.handler(response)

    async def goto(self, url, **kwargs):
        self.url = url

    async def wait_for_load_state(self, *args, **kwargs):
        if self.mode == "timeout":
            raise TimeoutError()

    def locator(self, selector):
        return self

    def nth(self, index):
        return self

    async def scroll_into_view_if_needed(self, **kwargs):
        pass

    async def evaluate(self, script):
        return {"clickable": self.mode != "obstructed", "blocker": "img"}

    async def is_visible(self):
        return self.mode != "hidden"

    async def select_option(self, value, **kwargs):
        self.state += 1

    async def click(self, **kwargs):
        if self.mode == "error":
            raise ValueError()
        if self.mode == "navigation":
            self.url = "https://example.org/detail/2"
        if self.mode != "static":
            self.state += 1


def response(body, ct="application/json", url="https://example.org/api/list", status=200):
    return SimpleNamespace(
        url=url,
        status=status,
        headers={"content-type": ct},
        request=SimpleNamespace(resource_type="xhr"),
        body=AsyncMock(return_value=body),
    )


class DynamicBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_expand_preserves_links_and_report(self):
        page = FakePage()
        html, report = await expand_readonly(page)
        self.assertIn("data-rag-dynamic", html)
        self.assertIn("https://example.org/detail/1", html)
        self.assertEqual(page.blocked, [1, 0, 0])
        self.assertGreater(report["clicked"], 0)
        self.assertEqual(report["no_change"], 1)

    async def test_navigation_errors_and_limits(self):
        for mode in ["navigation", "hidden", "error", "timeout"]:
            html, report = await expand_readonly(FakePage(mode=mode), max_actions=2)
            if mode == "navigation":
                self.assertIn("https://example.org/detail/2", report["revealed_links"])
            elif mode == "error":
                self.assertTrue(report["failures"])
            elif mode == "hidden":
                self.assertEqual(report["clicked"], 0)
            self.assertIn("<html>", html)
        _, report = await expand_readonly(FakePage(), max_actions=1, capture_initial=False)
        self.assertTrue(report["limit_reached"])

    async def test_dropdown_execution(self):
        page = FakePage()
        original = page.content

        async def content():
            return (await original()).replace(
                "<button>더보기</button>",
                '<select><option value="a" selected>A</option>'
                '<option value="b">B</option></select>',
            )

        page.content = content
        _, report = await expand_readonly(page, capture_initial=False)
        self.assertEqual(report["clicked"], 1)

    async def test_ajax_capture(self):
        responses = [
            response(json.dumps({"title": "AJAX artwork"}).encode()),
            response(b"<body>AJAX HTML</body>", "text/html"),
            response(b"invalid", "application/json"),
            response(b"x" * (1024 * 1024 + 1)),
            response(b"x", "image/png"),
            response(b"x", url="https://other.org/api"),
            response(b"x", status=403),
        ]
        html, report = await expand_readonly(FakePage(ajax=responses))
        self.assertIn("AJAX artwork", html)
        self.assertIn("AJAX HTML", html)
        self.assertEqual(len(report["ajax_urls"]), 2)
        self.assertIn("ajax_too_large", report["failures"])
        self.assertTrue(any("JSONDecodeError" in value for value in report["failures"]))


def test_user_input_search_is_not_explored():
    html = """<form><input type="text" name="keyword">
    <select><option value="seoul">서울</option></select>
    <button type="button" onclick="searchData()">조회</button>
    <a href="#" onclick="searchData(2)">다음</a></form>
    <button aria-expanded="false">펼치기</button>"""
    candidates = interaction_candidates(html)
    assert [c["label"] for c in candidates] == ["펼치기"]


def test_search_widget_and_external_form_controls_are_skipped():
    html = """<div class="postcode-search"><input type="search">
    <select><option value="1">서울</option></select><button>더보기</button></div>
    <form id="lookup"><textarea></textarea></form>
    <button form="lookup">조회</button>
    <a href="#" onclick="searchData(2)">다음페이지</a>
    <button role="tab">이용안내</button>"""
    assert [c["label"] for c in interaction_candidates(html)] == ["이용안내"]


class CycleBrowserTest(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_button_stops_on_previous_state(self):
        page = FakePage()

        async def content():
            return (
                "<html><body><main><button>더보기</button>"
                + ("상태 A" if page.state % 2 == 0 else "상태 B")
                + "</main></body></html>"
            )

        page.content = content
        _, report = await expand_readonly(page, capture_initial=False)
        self.assertEqual(report["clicked"], 2)
        self.assertEqual(report["repeated_states"], 1)
        self.assertFalse(report["limit_reached"])


@pytest.mark.asyncio
async def test_failed_navigation_restores_initial_page(isolate_readiness):
    from kspo_ingest.crawl.readiness import ContentReadinessError

    page = FakePage(mode="navigation")
    isolate_readiness.wait.side_effect = [
        ContentReadinessError("chrome-error://chromewebdata/"),
        {"ready": True},
    ]
    html, report = await expand_readonly(page, max_actions=2, capture_initial=False)
    assert page.url == "https://example.org/list"
    assert report["recovered_navigations"] == 1
    assert report["readiness_failures"]
    assert "<html>" in html


@pytest.mark.asyncio
async def test_arbitrary_post_routes_keep_write_and_external_requests_blocked():
    page = FakePage(mode="static")
    outcomes = []

    async def route(pattern, guard):
        for url in [
            "https://example.org/info/noticeList.kspo",
            "https://example.org/info/deleteList.kspo",
            "https://other.org/info/noticeList.kspo",
            "https://example.org/info/unknown.kspo",
            "https://example.org/info/noticelist.kspo",
            "https://example.org/info/update.kspo",
            "https://example.org/info/save.kspo",
            "https://example.org/info/apply.kspo",
        ]:
            r = SimpleNamespace(
                request=SimpleNamespace(method="POST", url=url),
                abort=AsyncMock(),
                continue_=AsyncMock(),
            )
            await guard(r)
            outcomes.append(r.abort.await_count)

    page.route = route
    await expand_readonly(page, capture_initial=False)
    assert outcomes == [0, 1, 1, 0, 0, 1, 1, 1]


@pytest.mark.asyncio
async def test_obstructed_controls_do_not_wait_or_force_click():
    page = FakePage(mode="obstructed")
    page.click = AsyncMock()
    html, report = await expand_readonly(page, capture_initial=False)
    page.click.assert_not_awaited()
    assert report["obstructed_controls"] == [{"action": "더보기", "blocker": "img"}]
    assert report["needs_review"]
    assert not report["failures"]
    assert "<html>" in html
