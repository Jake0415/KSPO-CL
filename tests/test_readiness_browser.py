"""Real Chromium checks against a local fixture site; no external requests."""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from kspo_ingest.crawl.readiness import ContentWaiter, ReadinessPolicy


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/obstructed-action":
            body = b"""<body><main>Valid public initial content</main>
            <div style="position:relative;width:150px;height:50px">
            <button style="width:150px;height:50px" onclick="throw Error('must not click')">
            More</button><div style="position:absolute;inset:0;background:white">Popup</div></div>
            <button onclick="expandInfo()">Details</button>
            <script>function expandInfo(){document.querySelector('main').innerText=
            'Second public content expanded'}</script></body>"""
        elif path == "/broken-action":
            body = b"""<body><main>Valid initial public content</main>
            <button onclick="openInfo()">More</button>
            <button onclick="expandInfo()">Details</button>
            <script>function openInfo(){location.href='/delete'}
            function expandInfo(){document.querySelector('main').innerText=
            'Second public content expanded'}</script>
            </body>"""
        elif path == "/start":
            body = (
                b"<body>Temporary landing content<script>"
                b'setTimeout(()=>location.replace("/final"),200)</script></body>'
            )
        elif path == "/final":
            body = b"""<body><main aria-busy="true">Loading public content</main>
            <button onclick="
            document.querySelector('main').setAttribute('aria-busy','true');
            fetch('/api').then(r=>r.text()).then(t=>{
            document.querySelector('main').innerText=t+' updated';
            document.querySelector('main').setAttribute('aria-busy','false')})">More</button>
            <script>fetch('/api').then(r=>r.text()).then(t=>{document.querySelector('main').innerText=t;document.querySelector('main').setAttribute('aria-busy','false')})</script></body>"""
        elif path == "/api":
            import time

            time.sleep(0.3)
            body = b"Public AJAX content fully available"
        else:
            body = b"<body>Public page content available</body>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.asyncio
async def test_real_redirect_and_dynamic_ajax_readiness():
    executable = os.environ.get("KSPO_TEST_BROWSER")
    if not executable:
        pytest.skip("Set KSPO_TEST_BROWSER to a local Chromium executable")
    from playwright.async_api import async_playwright

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    policy = ReadinessPolicy(initial_timeout_ms=5000, action_timeout_ms=3000, stable_ms=400)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            waiter = ContentWaiter(page, policy)
            waiter.host = "127.0.0.1"
            waiter.start()
            try:
                await page.goto(
                    f"http://127.0.0.1:{server.server_port}/start", wait_until="domcontentloaded"
                )
                result = await waiter.wait(initial=True)
                assert result["final_url"].endswith("/final")
                assert (
                    await page.locator("main").inner_text() == "Public AJAX content fully available"
                )
                before = await waiter.snapshot()
                await page.locator("button").click()
                result = await waiter.wait(initial=False, before=before)
                assert result["mode"] == "dynamic"
                assert not result["load_complete"]
                assert (await page.locator("main").inner_text()).endswith("updated")
                before = await waiter.snapshot()
                await page.reload(wait_until="domcontentloaded")
                result = await waiter.wait(initial=False, before=before)
                assert result["mode"] == "navigation"
            finally:
                waiter.close()
                await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()


@pytest.mark.asyncio
async def test_real_blocked_navigation_recovers_and_explores_next_button():
    executable = os.environ.get("KSPO_TEST_BROWSER")
    if not executable:
        pytest.skip("Set KSPO_TEST_BROWSER to a local Chromium executable")
    from playwright.async_api import async_playwright

    from kspo_ingest.crawl.dynamic import expand_readonly

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    policy = ReadinessPolicy(initial_timeout_ms=2000, action_timeout_ms=1000, stable_ms=200)
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            url = f"http://127.0.0.1:{server.server_port}/broken-action"
            await page.goto(url)
            html, report = await expand_readonly(page, max_actions=4, readiness_policy=policy)
            assert "Valid initial public content" in html
            assert "Second public content expanded" in html
            assert page.url == url
            assert report.get("recovered_navigations", 0) + len(report.get("navigations", [])) >= 1
            assert await page.locator("main").inner_text() == "Second public content expanded"
            assert any(u.endswith("/delete") for u in report["blocked_requests"])
            await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()


@pytest.mark.asyncio
async def test_real_overlay_is_reported_without_click_timeout():
    executable = os.environ.get("KSPO_TEST_BROWSER")
    if not executable:
        pytest.skip("Set KSPO_TEST_BROWSER to a local Chromium executable")
    from playwright.async_api import async_playwright

    from kspo_ingest.crawl.dynamic import expand_readonly

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path=executable, headless=True)
            page = await browser.new_page()
            await page.goto(f"http://127.0.0.1:{server.server_port}/obstructed-action")
            _, report = await expand_readonly(
                page,
                max_actions=4,
                readiness_policy=ReadinessPolicy(
                    initial_timeout_ms=2000, action_timeout_ms=1000, stable_ms=200
                ),
            )
            assert report["obstructed_controls"] == [{"action": "More", "blocker": "div"}]
            assert not report["failures"]
            assert await page.locator("main").inner_text() == "Second public content expanded"
            await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()


@pytest.mark.asyncio
async def test_real_browser_recovers_failed_probe_and_follows_input_redirect():
    executable = os.environ.get("KSPO_TEST_BROWSER")
    if not executable:
        pytest.skip("Set KSPO_TEST_BROWSER to a local Chromium executable")
    import time
    from unittest.mock import AsyncMock

    from playwright.async_api import async_playwright

    from kspo_ingest.crawl.browser import BrowserFetcher
    from kspo_ingest.crawl.domain_profile import (
        CrawlStrategy,
        DomainProfile,
        DomainProfiler,
        HealthStatus,
    )
    from kspo_ingest.crawl.smart_fetcher import SmartFetcher

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{server.server_port}"
    profiler = DomainProfiler()
    profiler._cache[host] = DomainProfile(
        host=host,
        strategy=CrawlStrategy.UNREACHABLE,
        health=HealthStatus.TIMEOUT,
        error="timeout",
        probed_at=time.time(),
    )
    http = AsyncMock()
    try:
        async with async_playwright() as pw:
            browser = BrowserFetcher(
                dynamic_max_actions=1,
                readiness_policy=ReadinessPolicy(
                    initial_timeout_ms=5000, action_timeout_ms=3000, stable_ms=400
                ),
            )
            browser._browser = await pw.chromium.launch(executable_path=executable, headless=True)
            smart = SmartFetcher(http_fetcher=http, browser_fetcher=browser, profiler=profiler)
            try:
                result = await smart.fetch(
                    f"http://{host}/start?marker=original", user_agent="test"
                )
                assert result.http_status == 200
                assert result.url == f"http://{host}/final"
                assert b"Public AJAX content fully available" in result.raw_bytes
                assert profiler.get_cached(host).strategy == CrawlStrategy.BROWSER
                assert profiler.get_cached(host).health == HealthStatus.HEALTHY
                http.fetch.assert_not_awaited()
            finally:
                await smart.close()
                await browser.close()
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
