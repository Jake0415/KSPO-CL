import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from kspo_ingest.crawl.external_fetch import fetch_external, validate_destination
from kspo_ingest.crawl.external_links import (
    discover_external_links,
    external_access_blocked,
    external_metadata,
    public_url,
)


class ExternalLinksTest(unittest.TestCase):
    def test_public_urls(self):
        for url in ["https://facebook.com/soma", "https://8.8.8.8/a"]:
            self.assertTrue(public_url(url))
        for url in [
            "javascript:x",
            "http://localhost/a",
            "http://a.local/x",
            "http://127.0.0.1",
            "http://10.0.0.1",
            "http://[::1]",
            "https://u:p@example.com",
            "https://example.com:8080",
            "https://example.com:abc",
            "http://intranet",
        ]:
            self.assertFalse(public_url(url))

    def test_external_references_only_one_hop(self):
        html = (
            '<a href="/main">Home</a><a href="https://facebook.com/soma">Facebook</a>'
            '<a href="https://facebook.com/soma#x">Duplicate</a>'
            '<a href="https://instagram.com/soma"><img alt="Instagram"></a>'
            '<a href="https://example.org/a" aria-label="Guide"></a>'
            '<a href="https://example.org/b"></a>'
            '<a href="https://facebook.com/sharer.php?u=x">Share</a>'
            '<a href="https://example.org/login">Login</a>'
            '<a href="https://example.org/a.pdf">PDF</a>'
            '<a href="http://127.0.0.1/">Private</a>'
        )
        links = discover_external_links(
            html, base_url="https://soma.kspo.or.kr/main", source_host="soma.kspo.or.kr"
        )
        self.assertEqual(len(links), 4)
        self.assertEqual(links[1].label, "Instagram")
        self.assertEqual(links[2].label, "Guide")
        self.assertEqual(links[3].label, "example.org")
        self.assertEqual(
            discover_external_links(html, base_url=links[0].url, source_host="soma.kspo.or.kr"), []
        )

    def test_access_wall(self):
        self.assertTrue(external_access_blocked('<input type="password">'))
        self.assertTrue(external_access_blocked('<meta content="Log into Facebook">'))
        self.assertFalse(external_access_blocked("<p>Public sculpture information</p>"))

    def test_public_metadata(self):
        title, body = external_metadata(
            '<meta property="og:title" content="SOMA">'
            '<meta property="og:description" content="Artwork details">'
            '<meta name="twitter:description" content="Artwork details">'
            '<meta property="og:site_name" content="Facebook">'
        )
        self.assertEqual(title, "SOMA")
        self.assertEqual(body.count("Artwork details"), 1)
        self.assertIn("Facebook", body)
        self.assertEqual(external_metadata("<p>None</p>"), (None, ""))


class Response:
    def __init__(self, status=200, headers=None, body=b"<p>Public</p>"):
        self.status_code = status
        self.headers = headers if headers is not None else {"content-type": "text/html"}
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self):
        yield self.body


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        self.urls.append(url)
        return next(self.responses)


class ExternalFetchTest(unittest.IsolatedAsyncioTestCase):
    async def test_dns_guard(self):
        with self.assertRaises(ValueError):
            await validate_destination("http://127.0.0.1")
        loop = SimpleNamespace(
            getaddrinfo=AsyncMock(return_value=[(0, 0, 0, "", ("8.8.8.8", 443))])
        )
        with patch.object(asyncio, "get_running_loop", return_value=loop):
            await validate_destination("https://example.org")
            for addresses in [[], [(0, 0, 0, "", ("127.0.0.1", 443))]]:
                loop.getaddrinfo.return_value = addresses
                with self.assertRaises(ValueError):
                    await validate_destination("https://example.org")

    async def run_fetch(self, responses):
        client = Client(responses)
        module = SimpleNamespace(AsyncClient=lambda **kwargs: client)
        with (
            patch.dict(sys.modules, {"httpx": module}),
            patch(
                "kspo_ingest.crawl.external_fetch.validate_destination", new=AsyncMock()
            ) as validate,
        ):
            result = await fetch_external("https://example.org", user_agent="test")
            self.assertEqual(validate.await_count, len(client.urls))
            return result

    async def test_success_and_redirect(self):
        result = await self.run_fetch([Response(302, {"location": "/post"}), Response()])
        self.assertEqual(result.http_status, 200)
        self.assertIn(b"Public", result.raw_bytes)
        result = await self.run_fetch([Response(403, {})])
        self.assertEqual(result.http_status, 403)

    async def test_errors(self):
        cases = [
            [Response(302, {})],
            [Response(200, {"content-type": "application/pdf"})],
            [Response(body=b"x" * (2 * 1024 * 1024 + 1))],
            [Response(302, {"location": "/next"}) for _ in range(6)],
        ]
        for responses in cases:
            with self.assertRaises(ValueError):
                await self.run_fetch(responses)
