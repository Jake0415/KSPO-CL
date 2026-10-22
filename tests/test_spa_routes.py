from types import SimpleNamespace

import pytest

from kspo_ingest.crawl.board import build_page_url, empty_board_reason, extract_board_items
from kspo_ingest.crawl.board_identity import board_key, is_detail_url
from kspo_ingest.crawl.board_validation import entry_url, validate_board
from kspo_ingest.crawl.dynamic import interaction_candidates, navigation_depth
from kspo_ingest.crawl.internal_links import discover_internal_links
from kspo_ingest.crawl.loop_guard import list_signature
from kspo_ingest.crawl.spa import effective_parts, is_spa_url
from kspo_ingest.crawl.start_url import browser_required, parse_start_url
from kspo_ingest.crawl.url_class import is_non_content_url
from kspo_ingest.crawl.url_normalize import canonical_url, normalize_url

BASE = "https://www.sports.re.kr/lib/"


def test_entry_and_fragment_identity():
    for prefix in ("#/", "#!/"):
        start = BASE + prefix
        assert parse_start_url(start) == start
        assert normalize_url(start)[0] == start
        detail = start + "search/detail/616263?offset=20&utm_source=test"
        assert canonical_url(detail).endswith(prefix + "search/detail/616263")
        assert normalize_url(detail)[1] == normalize_url(start + "search/detail/616263")[1]
        assert normalize_url(detail)[1] != normalize_url(start + "search/detail/616264")[1]
        assert normalize_url(start + "guide/hoo")[1] != normalize_url(start + "guide/map")[1]
    assert not is_spa_url("#content") and not is_spa_url("#//evil.example/x")
    assert normalize_url(BASE + "#content") == normalize_url(BASE)
    assert parse_start_url(BASE + "#content") == BASE


def test_router_query_canonicalization_and_document_separation():
    a = BASE + "?tenant=one#/guide/notice?max=20&offset=20&utm_source=x"
    b = BASE + "?tenant=one#/guide/notice?offset=20&max=20"
    assert normalize_url(a) == normalize_url(b)
    assert normalize_url(a)[1] != normalize_url(b.replace("offset=20", "offset=40"))[1]
    assert normalize_url(a)[1] != normalize_url(b.replace("tenant=one", "tenant=two"))[1]
    assert normalize_url(a)[1] == normalize_url(a.replace("https:", "http:"))[1]
    assert normalize_url(a)[0] == normalize_url(normalize_url(a)[0])[0]


def test_discovery_keeps_routes_but_blocks_anchors_accounts_and_input_search():
    html = '<a href="#/guide/hoo">Guide</a><a href="#/guide/map">Map</a>'
    html += '<a href="#content">Anchor</a><a href="#/login">Login</a>'
    html += '<a href="#/mylibrary/charges">Private</a><a href="#/delete">Delete</a>'
    html += '<a href="#/total-search?keyword=hello">User results</a>'
    html += '<a href="#/total-search?keyword=">Search screen</a>'
    html += '<a href="https://elsewhere.test/#/guide">External</a>'
    links = discover_internal_links(html, base_url=BASE + "#/", host="www.sports.re.kr")
    assert set(links) == {
        BASE + "#/guide/hoo",
        BASE + "#/guide/map",
        BASE + "#/total-search?keyword=",
    }
    assert is_non_content_url(BASE + "#/login")
    assert not is_non_content_url(BASE + "#/search/detail/616263")
    assert interaction_candidates('<a href="#/guide/map">More</a>') == []


def test_browser_selection_before_http_probe():
    domain = SimpleNamespace(use_playwright=False, host="www.sports.re.kr")
    assert browser_required(domain, BASE + "#/guide/map")
    assert not browser_required(domain, BASE)


@pytest.mark.asyncio
async def test_smart_fetch_routes_bypass_http_profiler():
    from unittest.mock import AsyncMock, Mock

    from kspo_ingest.crawl.smart_fetcher import SmartFetcher

    smart = object.__new__(SmartFetcher)
    browser = SimpleNamespace(fetch=AsyncMock(return_value="rendered"))
    smart._ensure_browser = AsyncMock(return_value=browser)
    smart._profiler = Mock()
    assert await smart.fetch(BASE + "#/guide/map", user_agent="test") == "rendered"
    smart._profiler.get_cached.assert_not_called()


def test_spa_board_identity_freshness_and_cursor_depth():
    url = BASE + "#/guide/notice?offset=40&max=20"
    assert entry_url(url, "www.sports.re.kr") == BASE + "#/guide/notice"
    assert entry_url(BASE + "#/guide/notice/45", "www.sports.re.kr") is None
    assert board_key(url) == board_key(url.replace("offset=40", "offset=0"))
    assert board_key(url) != board_key(BASE + "#/other/notice?max=20")
    assert is_detail_url(BASE + "#/search/detail/616263")
    assert navigation_depth(url, url.replace("offset=40", "offset=60"), 2) == 2
    assert navigation_depth(url, BASE + "#/guide/map", 2) == 3
    page2 = build_page_url(BASE + "#/guide/notice?max=20", 2, param="pageNo")
    assert effective_parts(page2).query == "max=20&offset=20"
    assert (
        effective_parts(build_page_url(BASE + "#/guide/notice?max=20", 1)).query
        == "max=20&offset=0"
    )
    assert build_page_url(BASE + "#/guide/notice", 2) == BASE + "#/guide/notice"
    html = (
        "<main><table><tr><th>등록일</th></tr>"
        + "".join(
            f'<tr><td><a href="#/guide/notice/{n}">Article {n}</a></td>'
            '<td class="date">2026-10-22</td></tr>'
            for n in (45, 46)
        )
        + "</table></main>"
    )
    items = extract_board_items(html, base_url=url)
    assert len(items) == 2 and all("/#/guide/notice/" in it.url for it in items)
    validation = validate_board(html, url, "www.sports.re.kr")
    assert validation.valid, validation
    assert empty_board_reason(html, base_url=url) == "unparsed_list"
    assert list_signature(url, [it.url for it in items])
    assert list_signature(url, [it.url for it in items]) == list_signature(
        page2, [it.url for it in items]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_url", [BASE + "#/", BASE + "#/guide/hoo", "www.sports.re.kr/lib/#/"]
)
async def test_crawl_api_preserves_exact_seed_through_entry_and_preflight(monkeypatch, input_url):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from kspo_ingest.api.deps import db_session, require_admin
    from kspo_ingest.api.routers import jobs
    from kspo_ingest.crawl.start_url import entry_urls, preflight_start

    domain = SimpleNamespace(
        id=7,
        host="www.sports.re.kr",
        is_active=True,
        use_playwright=False,
        start_url=None,
        user_agent="test",
        rate_limit_rps=1.5,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: domain))
    )
    seed = parse_start_url(input_url)
    job = SimpleNamespace(
        id=1,
        domain_id=7,
        job_type="full",
        seed_urls=[seed],
        status="PENDING",
        triggered_by="admin",
        created_at=datetime.now(UTC),
    )
    trigger = AsyncMock(return_value=job)
    monkeypatch.setattr(jobs, "_trigger_job", trigger)
    app = FastAPI()
    app.include_router(jobs.router)
    app.dependency_overrides[db_session] = lambda: session
    app.dependency_overrides[require_admin] = lambda: "test-admin"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/jobs/crawl", json={"input": input_url, "job_type": "full"}
        )
    assert response.status_code == 201, response.text
    assert response.json()["job"]["seed_urls"] == [seed]
    assert trigger.call_args.kwargs["seed_urls"] == [seed]
    assert entry_urls(domain, job) == [seed]
    assert entry_urls(SimpleNamespace(host=domain.host, start_url=seed), None) == [seed]
    from kspo_ingest.crawl import external_fetch

    monkeypatch.setattr(external_fetch, "validate_destination", AsyncMock())
    browser = SimpleNamespace(
        fetch=AsyncMock(
            return_value=SimpleNamespace(
                url=seed,
                http_status=200,
                raw_bytes=(
                    b'<main>Public library content ready</main><a href="#/guide/hoo">Guide</a>'
                ),
            )
        )
    )
    http = SimpleNamespace(fetch=AsyncMock(side_effect=AssertionError("must use browser")))
    ctx = {
        "playwright_fetcher": browser,
        "fetcher": http,
        "rate_limit": SimpleNamespace(acquire=AsyncMock()),
    }
    await preflight_start(ctx, domain, [seed])
    assert browser.fetch.call_args.args[0] == seed
    http.fetch.assert_not_called()


def test_spa_next_page_prefers_visible_links_and_keeps_filters():
    from kspo_ingest.crawl.board import next_spa_page_url

    current = BASE + "#/guide/notice?offset=0&max=20"
    html = (
        '<a href="#/guide/notice?offset=40&max=20">3</a>'
        '<a href="#/guide/notice?offset=20&max=20">2</a>'
    )
    assert next_spa_page_url(html, current, 1) == BASE + "#/guide/notice?offset=20&max=20"
    assert next_spa_page_url("", current, 1).endswith("max=20&offset=20")
    assert next_spa_page_url("", BASE + "#/guide/notice", 1) is None
    assert entry_url(current, "www.sports.re.kr") == entry_url(
        BASE + "#/guide/notice", "www.sports.re.kr"
    )


@pytest.mark.asyncio
async def test_frontier_keeps_router_seed_in_queue():
    import json
    from unittest.mock import AsyncMock

    from kspo_ingest.crawl.frontier import Frontier

    redis = SimpleNamespace(get=AsyncMock(return_value=30000), eval=AsyncMock(return_value=1))
    frontier = Frontier(redis)
    frontier.reserve_discovery = AsyncMock(return_value=True)
    seed = BASE + "#/"
    assert await frontier.enqueue(1, seed, depth=0)
    assert json.loads(redis.eval.call_args.args[-1]) == {"url": seed, "depth": 0}


def test_spa_article_ownership_and_cursor_variants():
    from kspo_ingest.crawl.board_identity import is_board_owned_link

    article = BASE + "#/guide/notice/45"
    assert is_detail_url(article)
    assert normalize_url(article)[1] == normalize_url(article + "?offset=20&max=20")[1]
    assert is_board_owned_link(article, confirmed_list_urls={BASE + "#/guide/notice"})
