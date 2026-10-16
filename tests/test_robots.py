from __future__ import annotations

import httpx
import pytest
import respx

from kspo_ingest.crawl.robots import RobotsCache


@pytest.mark.asyncio
async def test_robots_disallow_specific_path():
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nDisallow: /admin/\n")
        )
        rc = RobotsCache()
        assert await rc.is_allowed("https://x.com/admin/foo", "ua") is False
        assert await rc.is_allowed("https://x.com/public", "ua") is True


@pytest.mark.asyncio
async def test_robots_fail_open_on_5xx():
    """robots.txt 가 5xx → 보수적으로 allow."""
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/robots.txt").mock(return_value=httpx.Response(500))
        rc = RobotsCache()
        assert await rc.is_allowed("https://x.com/anywhere", "ua") is True


@pytest.mark.asyncio
async def test_robots_fail_open_on_404():
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/robots.txt").mock(return_value=httpx.Response(404))
        rc = RobotsCache()
        assert await rc.is_allowed("https://x.com/page", "ua") is True


@pytest.mark.asyncio
async def test_robots_fail_open_on_network_error():
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("https://x.com/robots.txt").mock(side_effect=httpx.ConnectError("boom"))
        rc = RobotsCache()
        assert await rc.is_allowed("https://x.com/page", "ua") is True


@pytest.mark.asyncio
async def test_robots_per_host_cached():
    """동일 host 두번째 호출은 cache 사용 (단 1 fetch)."""
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://x.com/robots.txt").mock(
            return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
        )
        rc = RobotsCache()
        await rc.is_allowed("https://x.com/a", "ua")
        await rc.is_allowed("https://x.com/b", "ua")
    assert route.call_count == 1
