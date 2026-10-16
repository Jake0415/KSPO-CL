from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.dynamic import expand_readonly, interaction_candidates
from kspo_ingest.crawl.smart_fetcher import SmartFetcher
from tests.test_dynamic_crawl import FakePage
from tests.test_dynamic_crawl import isolate_readiness as isolate_readiness


@pytest.mark.asyncio
async def test_preflight_skips_expansion_and_clears_old_navigation():
    browser = SimpleNamespace(
        fetch=AsyncMock(return_value="ready"), _navigation_cache={"old": {"link"}}
    )
    smart = SmartFetcher(browser_fetcher=browser)
    assert await smart.fetch_preflight("https://example.org/", user_agent="test") == "ready"
    browser.fetch.assert_awaited_once_with("https://example.org/", user_agent="test", explore=False)
    assert not browser._navigation_cache


def test_content_tabs_are_never_shared_navigation():
    candidates = interaction_candidates(
        '<nav><a href="#">메뉴</a><a role="tab" href="#">탭</a></nav>'
        "<main><button>더보기</button></main>"
    )
    assert candidates[0]["navigation_key"]
    assert not candidates[1]["navigation_key"]
    assert not candidates[2]["navigation_key"]
    changed = interaction_candidates('<nav><a href="#">다른 메뉴</a></nav>')
    assert changed[0]["navigation_key"] != candidates[0]["navigation_key"]


class NavigationPage(FakePage):
    async def content(self):
        link = '<a href="/found">안내</a>' if self.state else ""
        return (
            '<html><body><nav><a href="#">메뉴</a>'
            + link
            + "</nav><main>페이지 본문</main></body></html>"
        )


@pytest.mark.asyncio
async def test_reuses_navigation_links_without_clicking_or_losing_body():
    cache = {}
    _, first = await expand_readonly(NavigationPage(), navigation_cache=cache)
    assert first["clicked"] > 0
    html, second = await expand_readonly(NavigationPage(), navigation_cache=cache)
    assert second["clicked"] == 0
    assert second["navigation_cache_hits"] == 1
    assert "https://example.org/found" in html
    assert "페이지 본문" in html


@pytest.mark.asyncio
async def test_body_expansion_is_not_cached():
    cache = {}
    await expand_readonly(FakePage(), navigation_cache=cache)
    _, second = await expand_readonly(FakePage(), navigation_cache=cache)
    assert not cache
    assert second["clicked"] > 0


def test_header_menu_button_is_shared_but_body_button_is_not():
    candidates = interaction_candidates(
        '<div id="header"><button>전체메뉴</button></div><main><button>더보기</button></main>'
    )
    assert candidates[0]["navigation_key"]
    assert not candidates[1]["navigation_key"]


@pytest.mark.asyncio
async def test_cancelled_retry_does_not_restart_or_reset_site():
    from unittest.mock import MagicMock

    from kspo_ingest.db.models import Domain
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_seeds_impl

    session = AsyncMock()
    session.get.side_effect = lambda model, key: (
        SimpleNamespace(host="example.org")
        if model is Domain
        else SimpleNamespace(status="CANCELLED")
    )
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    sonar = SimpleNamespace(reset_site=AsyncMock())
    await _enqueue_seeds_impl(
        {"session_factory": factory, "frontier": AsyncMock(), "sonar_client": sonar},
        job_id=1,
        domain_id=1,
    )
    sonar.reset_site.assert_not_awaited()
    session.execute.assert_not_awaited()
