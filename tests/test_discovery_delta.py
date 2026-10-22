from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.url_class import is_non_content_url, is_search_result_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sports.re.kr/lib/#/search/si?author=1%7Cm%7Ca%7Cname",
        "https://www.sports.re.kr/lib/#/search/ex?all=title&subject=exercise",
        "https://www.sports.re.kr/lib/#/search/tempitems?max=20&offset=20",
        "https://example.kr/#!/search/si?facet=book&sort=date",
        "https://example.kr/catalog/search?author=Kim",
        "https://example.kr/searchResult.do?filter=adult",
        "https://example.kr/board/list.do?bid=1&searchWrd=exercise",
    ],
)
def test_generated_search_states_are_excluded(url):
    assert is_search_result_url(url)
    assert is_non_content_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sports.re.kr/lib/#/",
        "https://www.sports.re.kr/lib/#/search/si",
        "https://example.kr/search?keyword=",
        "https://www.sports.re.kr/lib/#/search/detail/616263",
        "https://www.sports.re.kr/lib/#/search/detail/616263?author=Kim",
        "https://example.kr/board/list.do?bid=65&nPage=2&searchWrd=",
        "https://example.kr/research/project/orginView.do?artctrlno=IR_616130",
        "https://example.kr/content/detail?id=5&category=exercise",
    ],
)
def test_forms_details_and_board_pagination_are_preserved(url):
    assert not is_search_result_url(url)
    assert not is_non_content_url(url)


@pytest.mark.asyncio
async def test_frontier_blocks_search_even_when_seeded_directly():
    from kspo_ingest.crawl.frontier import Frontier

    redis = AsyncMock()
    frontier = Frontier(redis)
    url = "https://x.kr/lib/#/search/ex?author=Kim"
    assert not await frontier.enqueue(1, url, 1)
    assert not await frontier.reserve_discovery(1, url, limit=30000)
    assert not await frontier.admit_direct(1, url)
    redis.eval.assert_not_awaited()
    redis.get.assert_not_awaited()


def test_search_filtered_after_redirect_and_specialized_discovery():
    from kspo_ingest.tasks.pipeline.extract_links import crawlable_link_urls

    html = """<a href="/lib/#/search/si?author=Kim">author</a>
      <a href="/lib/#/search/detail/10">detail</a>
      <a href="/lib/#/search/si">form</a>
      <meta http-equiv="refresh" content="0;url=/lib/#/search/ex?all=book">"""
    urls = crawlable_link_urls(html, base_url="https://x.kr/lib/#/", host="x.kr")
    assert "https://x.kr/lib/#/search/detail/10" in urls
    assert "https://x.kr/lib/#/search/si" in urls
    assert not any(is_search_result_url(url) for url in urls)


def queue_context(pending):
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        )
    )

    class Scope:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            pass

    return {
        "session_factory": Scope,
        "frontier": SimpleNamespace(enqueue=AsyncMock(return_value=True)),
        "new_discoveries": pending,
    }, session


@pytest.mark.asyncio
async def test_empty_delta_never_queries_database_or_redis():
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_discovered

    ctx, session = queue_context([])
    for _ in range(20):
        assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 0
    session.execute.assert_not_awaited()
    ctx["frontier"].enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_drains_only_new_rows_including_board_discoveries():
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_discovered

    ctx, session = queue_context([("https://x.kr/a", 1)])
    board_ctx = dict(ctx)
    board_ctx["new_discoveries"].append(("https://x.kr/from-board", 2))
    assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 2
    assert ctx["new_discoveries"] == []
    assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 0
    assert ctx["frontier"].enqueue.await_count == 2
    assert session.execute.await_count == 1
    # The only SELECT is board ownership; no pages/backlog scan.
    assert "FROM pages" not in str(session.execute.call_args.args[0])


@pytest.mark.asyncio
async def test_queue_error_retains_unprocessed_suffix_for_retry():
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_discovered

    ctx, _ = queue_context([("https://x.kr/a", 1), ("https://x.kr/b", 1)])
    ctx["frontier"].enqueue.side_effect = [True, ConnectionError("Redis unavailable")]
    with pytest.raises(ConnectionError):
        await _enqueue_discovered(ctx, job_id=1, domain_id=19)
    assert ctx["new_discoveries"] == [("https://x.kr/b", 1)]
    ctx["frontier"].enqueue.side_effect = None
    assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 1
    assert not ctx["new_discoveries"]


@pytest.mark.asyncio
async def test_only_committed_insert_returning_rows_enter_delta():
    from kspo_ingest.tasks.pipeline.extract_links import _upsert_discovered_pages

    new_pages = []
    statements = []

    async def execute(stmt):
        statements.append(stmt)
        if str(stmt).startswith("SELECT"):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        assert "RETURNING pages.url, pages.depth" in str(stmt)
        # a already exists; PostgreSQL returns only the inserted b row.
        return SimpleNamespace(all=lambda: [("https://x.kr/b", 1)])

    async def commit():
        assert new_pages == []

    count = await _upsert_discovered_pages(
        SimpleNamespace(execute=execute, commit=commit),
        page=SimpleNamespace(url="https://x.kr/", domain_id=19, depth=0, storage_paths={}),
        domain=SimpleNamespace(id=19, host="x.kr", max_depth=10, max_pages=30000),
        html='<a href="/a">old</a><a href="/b">new</a>',
        new_pages=new_pages,
    )
    assert count == 1
    assert new_pages == [("https://x.kr/b", 1)]


@pytest.mark.asyncio
async def test_failed_commit_does_not_enqueue_uncommitted_rows():
    from kspo_ingest.tasks.pipeline.extract_links import _upsert_discovered_pages

    ctx, _ = queue_context([])
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
                SimpleNamespace(all=lambda: [("https://x.kr/b", 1)]),
            ]
        ),
        commit=AsyncMock(side_effect=RuntimeError("rollback")),
    )
    with pytest.raises(RuntimeError):
        await _upsert_discovered_pages(
            session,
            page=SimpleNamespace(url="https://x.kr/", domain_id=19, depth=0, storage_paths={}),
            domain=SimpleNamespace(id=19, host="x.kr", max_depth=10, max_pages=30000),
            html='<a href="/b">new</a>',
            new_pages=ctx["new_discoveries"],
        )
    assert ctx["new_discoveries"] == []


@pytest.mark.asyncio
async def test_extract_links_delivers_new_insert_to_full_job_frontier(tmp_path, monkeypatch):
    import fakeredis.aioredis

    from kspo_ingest.crawl.frontier import Frontier
    from kspo_ingest.db.models import Domain, Page
    from kspo_ingest.tasks.pipeline import extract_links as links
    from kspo_ingest.tasks.pipeline.enqueue_seeds import _enqueue_discovered

    raw = tmp_path / "page.html"
    raw.write_text('<a href="/a">old</a><a href="/b">new</a>', encoding="utf-8")
    page = SimpleNamespace(
        id=1,
        url="https://x.kr/",
        url_hash="a" * 40,
        domain_id=19,
        depth=0,
        storage_paths={},
        content_type="text/html",
    )
    domain = SimpleNamespace(id=19, host="x.kr", max_depth=10, max_pages=30000)

    async def get(model, ident):
        return page if model is Page else domain if model is Domain else None

    statements = []

    async def execute(stmt):
        statements.append(str(stmt))
        if str(stmt).startswith("SELECT"):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        return SimpleNamespace(all=lambda: [("https://x.kr/b", 1)])

    session = SimpleNamespace(get=get, execute=execute, commit=AsyncMock())

    class Scope:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(links, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(links, "_upsert_attachments", AsyncMock(return_value=0))
    monkeypatch.setattr(links.storage_paths, "raw_path", lambda *a: raw)
    monkeypatch.setattr(
        links, "classify_board_list", lambda *a, **kw: SimpleNamespace(is_board=False)
    )
    redis = fakeredis.aioredis.FakeRedis()
    try:
        ctx = {
            "session_factory": Scope,
            "frontier": Frontier(redis),
            "new_discoveries": [],
            "storage_root": tmp_path,
            "full_url_limit": 30000,
        }
        result = await links.extract_links(ctx, job_id=1, page_id=1)
        assert result["discovered"] == 1
        assert ctx["new_discoveries"] == [("https://x.kr/b", 1)]
        assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 1
        assert await _enqueue_discovered(ctx, job_id=1, domain_id=19) == 0
        assert await ctx["frontier"].size(1) == 1
        assert await ctx["frontier"].dequeue(1) == ("https://x.kr/b", 1)
        assert not any("FROM pages" in stmt for stmt in statements)
        assert await redis.get("duplicates:1") is None
    finally:
        await redis.aclose()
