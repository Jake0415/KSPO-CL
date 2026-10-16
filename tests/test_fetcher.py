from __future__ import annotations

import httpx
import pytest
import respx

from kspo_ingest.crawl.fetcher import Fetcher, ResponseTooLargeError


@pytest.mark.asyncio
async def test_fetch_200_returns_body_and_metadata():
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/a").mock(
            return_value=httpx.Response(
                200, content=b"<html/>", headers={"content-type": "text/html"}
            )
        )
        f = Fetcher()
        r = await f.fetch("https://x.com/a", user_agent="kspo-ingest/test")
    assert r.http_status == 200
    assert r.raw_bytes == b"<html/>"
    assert r.content_type.startswith("text/html")
    assert r.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_fetch_5xx_retries_until_success():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://x.com/a")
        route.side_effect = [
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, content=b"ok"),
        ]
        f = Fetcher()
        r = await f.fetch("https://x.com/a", user_agent="ua")
    assert r.http_status == 200
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_fetch_4xx_no_retry():
    """4xx는 retry 없이 그대로 반환."""
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://x.com/missing").mock(return_value=httpx.Response(404))
        f = Fetcher()
        r = await f.fetch("https://x.com/missing", user_agent="ua")
    assert r.http_status == 404
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_fetch_response_too_large_via_body():
    async with respx.mock(assert_all_called=False) as mock:
        big = b"x" * (11 * 1024 * 1024)
        mock.get("https://x.com/big").mock(return_value=httpx.Response(200, content=big))
        f = Fetcher(max_response_bytes=10 * 1024 * 1024)
        with pytest.raises(ResponseTooLargeError):
            await f.fetch("https://x.com/big", user_agent="ua")


@pytest.mark.asyncio
async def test_fetch_response_too_large_via_content_length_header():
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/big2").mock(
            return_value=httpx.Response(
                200, content=b"hi", headers={"content-length": str(11 * 1024 * 1024)}
            )
        )
        f = Fetcher(max_response_bytes=10 * 1024 * 1024)
        with pytest.raises(ResponseTooLargeError):
            await f.fetch("https://x.com/big2", user_agent="ua")


@pytest.mark.asyncio
async def test_fetch_user_agent_propagated():
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://x.com/").mock(return_value=httpx.Response(200, content=b""))
        f = Fetcher()
        await f.fetch("https://x.com/", user_agent="kspo-ingest/0.2")
        sent = route.calls.last.request
        assert sent.headers.get("user-agent") == "kspo-ingest/0.2"


@pytest.mark.asyncio
async def test_fetch_sends_self_referer():
    """Referer 게이트 사이트(nfa.kspo.or.kr 등) 대응 — origin self-referer 전송.

    Referer 헤더가 없으면 302로 랜딩 게이트로 되돌리는 서버가 있어,
    브라우저와 동일하게 same-origin Referer(scheme://host/)를 붙인다.
    """
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://nfa.kspo.or.kr/main.kspo").mock(
            return_value=httpx.Response(200, content=b"<html/>")
        )
        f = Fetcher()
        await f.fetch("https://nfa.kspo.or.kr/main.kspo", user_agent="ua")
        sent = route.calls.last.request
        assert sent.headers.get("referer") == "https://nfa.kspo.or.kr/"


@pytest.mark.asyncio
async def test_js_redirect_follow_sends_referer():
    """JS redirect 팔로우 요청에도 Referer(원본 셸 URL)를 붙인다."""
    async with respx.mock(assert_all_called=False) as mock:
        shell = b'<html><head><script>location.href="/main.kspo";</script></head></html>'
        mock.get("https://nfa.kspo.or.kr/").mock(
            return_value=httpx.Response(200, content=shell)
        )
        target = mock.get("https://nfa.kspo.or.kr/main.kspo").mock(
            return_value=httpx.Response(200, content=b"<html>real</html>")
        )
        f = Fetcher()
        r = await f.fetch("https://nfa.kspo.or.kr/", user_agent="ua")
        assert r.raw_bytes == b"<html>real</html>"
        assert target.calls.last.request.headers.get("referer") == "https://nfa.kspo.or.kr/"
