"""Real browser SPA collection against local fixtures; no DB/LLM/external writes."""

import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            import time

            time.sleep(1)
            body = ("Public routed content for " + self.path).encode()
        else:
            body = b"""<body><header>Permanent library navigation and shell content</header>
            <a href="#/guide">Guide</a><a href="#/detail/42">Detail</a>
            <a href="#content">Anchor</a><div ng-view aria-busy="true"></div>
            <script>
            function render(){const node=document.querySelector('[ng-view]');
              node.setAttribute('aria-busy','true');
              fetch('/api/'+location.hash.slice(2)).then(r=>r.text()).then(text=>{
                node.innerHTML='<main>'+text+'</main>';
                node.setAttribute('aria-busy','false');});}
            window.addEventListener('hashchange', render);render();
            </script></body>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.asyncio
async def test_rendered_hash_pages_are_separate_and_route_change_waits_for_ajax():
    if not os.environ.get("KSPO_TEST_BROWSER"):
        pytest.skip("Set KSPO_TEST_BROWSER to enable real browser tests")
    from playwright.async_api import async_playwright

    from kspo_ingest.crawl.browser import BrowserFetcher
    from kspo_ingest.crawl.internal_links import discover_internal_links
    from kspo_ingest.crawl.readiness import ContentWaiter, ReadinessPolicy
    from kspo_ingest.crawl.url_normalize import normalize_url

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/lib/"
    policy = ReadinessPolicy(initial_timeout_ms=5000, action_timeout_ms=4000, stable_ms=250)
    fetcher = BrowserFetcher(readiness_policy=policy, dynamic_max_actions=3)
    try:
        guide = await fetcher.fetch(base + "#/guide", explore=True)
        detail = await fetcher.fetch(base + "#/detail/42", explore=False)
        assert guide.url.endswith("#/guide") and detail.url.endswith("#/detail/42")
        assert b"Public routed content for /api/guide" in guide.raw_bytes
        assert b"Public routed content for /api/detail/42" not in guide.raw_bytes
        assert b"Public routed content for /api/detail/42" in detail.raw_bytes
        assert normalize_url(guide.url)[1] != normalize_url(detail.url)[1]
        assert base + "#/detail/42" in discover_internal_links(
            guide.raw_bytes.decode(), base_url=guide.url, host=f"127.0.0.1:{server.server_port}"
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await browser.new_page()
            await page.goto(base + "#/guide")
            waiter = ContentWaiter(page, policy)
            waiter.host = "127.0.0.1"
            waiter.start()
            await waiter.wait(initial=True)
            before = await waiter.snapshot()
            await page.get_by_role("link", name="Detail", exact=True).click()
            result = await waiter.wait(initial=False, before=before)
            assert result["mode"] == "dynamic" and not result["load_complete"]
            assert (
                await page.locator("main").inner_text()
                == "Public routed content for /api/detail/42"
            )
            waiter.close()
            await browser.close()
    finally:
        await fetcher.close()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
