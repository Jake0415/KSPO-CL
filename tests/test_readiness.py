import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.crawl import readiness as mod
from kspo_ingest.crawl.readiness import ContentReadinessError, ContentWaiter, ReadinessPolicy


def state(url="https://example.org/page", doc=1, fingerprint="A", length=100, loading=False):
    return {
        "url": url,
        "document_id": doc,
        "fingerprint": fingerprint,
        "text_length": length,
        "ready_state": "complete",
        "loading": loading,
    }


class Clock:
    now = 0.0

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(mod, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(
        mod, "asyncio", SimpleNamespace(sleep=clock.sleep, wait_for=asyncio.wait_for)
    )
    return clock


def page_with_states(states):
    page = MagicMock(url="https://example.org/page")
    states = list(states)

    def snapshot(*args):
        return states.pop(0) if len(states) > 1 else states[0]

    page.evaluate = AsyncMock(side_effect=snapshot)
    page.wait_for_load_state = AsyncMock()
    return page


@pytest.mark.asyncio
async def test_initial_waits_through_empty_and_redirects_until_final_content(clock):
    page = page_with_states(
        [
            state(length=0),
            state(url="https://example.org/final", doc=2),
            state(url="https://example.org/final", doc=2, fingerprint="B"),
        ]
    )
    result = await ContentWaiter(page).wait(initial=True)
    assert result["mode"] == "navigation"
    assert result["final_url"] == "https://example.org/final"
    assert result["ready"] and clock.now >= 0.8
    page.wait_for_load_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_dynamic_does_not_wait_for_full_document_load(clock):
    page = page_with_states([state(fingerprint="B")])
    result = await ContentWaiter(page).wait(initial=False, before=state())
    assert result["mode"] == "dynamic"
    page.wait_for_load_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_url_document_reload_switches_to_navigation(clock):
    page = page_with_states([state(doc=2)])
    result = await ContentWaiter(page).wait(initial=False, before=state(doc=1))
    assert result["mode"] == "navigation"
    page.wait_for_load_state.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", [state(length=0), state(loading=True)])
async def test_empty_or_busy_content_is_never_ready(clock, sample):
    page = page_with_states([sample])
    with pytest.raises(ContentReadinessError, match="content_not_stable_or_empty"):
        await ContentWaiter(page, ReadinessPolicy(action_timeout_ms=1100)).wait(initial=False)


@pytest.mark.asyncio
async def test_waits_for_same_host_ajax_but_ignores_tracking_and_other_hosts(clock):
    page = page_with_states([state()])
    waiter = ContentWaiter(page).start()
    request = SimpleNamespace(resource_type="xhr", url="https://example.org/api/details")
    waiter._request(request)
    assert len(waiter.pending) == 1
    waiter._request(SimpleNamespace(resource_type="fetch", url="https://example.org/analytics"))
    waiter._request(SimpleNamespace(resource_type="fetch", url="https://tracker.org/api"))
    assert len(waiter.pending) == 1
    with pytest.raises(ContentReadinessError, match="pending_ajax"):
        await waiter.wait(initial=False, before=state())
    waiter._finished(request)
    assert (await waiter.wait(initial=False, before=state()))["ready"]
    waiter.close()
    assert page.remove_listener.call_count == 3


@pytest.mark.asyncio
async def test_slow_background_load_can_finish_with_ready_content(clock):
    page = page_with_states([state()])
    page.wait_for_load_state.side_effect = TimeoutError("background resource")
    result = await ContentWaiter(page).wait(initial=True)
    assert result["ready"] and not result["load_complete"]


@pytest.mark.asyncio
async def test_disappearing_context_during_redirect_is_retried(clock):
    page = page_with_states([state()])
    page.evaluate.side_effect = [
        RuntimeError("execution context destroyed"),
        state(),
        *[state()] * 20,
    ]
    assert (await ContentWaiter(page).wait(initial=True))["ready"]


@pytest.mark.asyncio
async def test_readiness_failure_does_not_fall_back_to_http():
    from kspo_ingest.crawl.smart_fetcher import SmartFetcher

    http = SimpleNamespace(fetch=AsyncMock())
    browser = SimpleNamespace(fetch=AsyncMock(side_effect=ContentReadinessError("empty")))
    fetcher = SmartFetcher(http_fetcher=http, browser_fetcher=browser, auto_probe=False)
    with pytest.raises(ContentReadinessError):
        await fetcher._browser_or_http("https://example.org/page", user_agent="test")
    http.fetch.assert_not_awaited()
