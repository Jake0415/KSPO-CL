from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import BoardSource, Domain

GOOD = (
    "<main><table><tr><th>게시일</th></tr>"
    + "".join(
        f'<tr><td><a href="/view.do?nttId={n}">글</a></td><td>2026.10.13</td></tr>' for n in (1, 2)
    )
    + "</table></main>"
)


@pytest.mark.asyncio
async def test_existing_page_does_not_stop_next_page_and_date_boundary(monkeypatch):
    from kspo_ingest.tasks.pipeline import run_board_refresh as module

    now = datetime.now(UTC)
    source = SimpleNamespace(id=1, list_url="https://x.kr/bbs/list.do", newest_first=True)
    domain = SimpleNamespace(host="x.kr", user_agent=None, rate_limit_rps=1)
    old_hash = normalize_url("https://x.kr/view.do?nttId=1")[1]

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, ident):
            return domain if model is Domain else source if model is BoardSource else None

        async def execute(self, statement):
            if "board_source" in str(statement):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [source]))
            return SimpleNamespace(all=lambda: [(old_hash,)])

        async def commit(self):
            pass

    requested = []

    async def fetch(url, **kwargs):
        from urllib.parse import parse_qs, urlsplit

        number = int(parse_qs(urlsplit(url).query)["pageIndex"][0])
        requested.append(number)
        posted = now - timedelta(days=1 if number <= 2 else 150)
        html = (
            f'<table><tr><td><a href="/view.do?nttId={number}">글</a></td>'
            f"<td>{posted:%Y.%m.%d}</td></tr></table>"
        )
        return SimpleNamespace(
            http_status=200, raw_bytes=html.encode(), content_type="text/html;charset=utf-8"
        )

    process = AsyncMock()
    finish = AsyncMock()
    monkeypatch.setattr(module, "process_board_page", process)
    monkeypatch.setattr(
        "kspo_ingest.crawl.board_detect.revalidate_source", AsyncMock(return_value=source.list_url)
    )
    monkeypatch.setattr(module, "start_job", AsyncMock())
    monkeypatch.setattr(module, "finish_job", finish)
    monkeypatch.setattr(module, "finish_crawl_job", finish)
    monkeypatch.setattr(module, "is_cancelled", AsyncMock(return_value=False))
    await module._run_board_refresh_impl(
        {
            "session_factory": Session,
            "smart_fetcher": SimpleNamespace(fetch=fetch),
            "rate_limit": SimpleNamespace(acquire=AsyncMock()),
        },
        job_id=1,
        domain_id=1,
    )
    assert requested == [1, 2, 3, 4]
    assert process.await_count == 1
    assert process.call_args.kwargs["url"].endswith("nttId=2")
    finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_automatic_registration_and_rejection_preserved():
    from kspo_ingest.crawl.board_detect import upsert_board_candidate

    class Session:
        def __init__(self, existing=None):
            self.existing = existing
            self.added = []

        async def get(self, model, ident):
            return SimpleNamespace(host="x.kr", user_agent=None)

        async def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: self.existing)

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            pass

    fresh = Session()
    await upsert_board_candidate(
        fresh,
        domain_id=1,
        list_url="https://x.kr/news/list",
        html=GOOD,
        fetched_url="https://x.kr/news/list",
    )
    assert fresh.added[0].status == "confirmed"
    assert fresh.added[0].confirmed_at
    rejected = SimpleNamespace(status="rejected")
    await upsert_board_candidate(
        Session(rejected),
        domain_id=1,
        list_url="https://x.kr/news/list",
        html=GOOD,
        fetched_url="https://x.kr/news/list",
    )
    assert rejected.status == "rejected"
    candidate = SimpleNamespace(status="candidate", confirmed_at=None)
    await upsert_board_candidate(
        Session(candidate),
        domain_id=1,
        list_url="https://x.kr/news/list",
        html=GOOD,
        fetched_url="https://x.kr/news/list",
    )
    assert candidate.status == "confirmed"


@pytest.mark.asyncio
async def test_full_resets_site_board_sources_and_data_before_rediscovery(monkeypatch, tmp_path):
    import fakeredis.aioredis

    from kspo_ingest.crawl.frontier import Frontier
    from kspo_ingest.db.models import CrawlJob
    from kspo_ingest.tasks.pipeline import enqueue_seeds as module
    from kspo_ingest.tasks.pipeline import run_board_refresh as board

    events = []
    domain = SimpleNamespace(host="x.kr", scheme="https", max_pages=9999, max_depth=10)
    job = CrawlJob(id=1, domain_id=1, job_type="full", stats={})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, ident):
            return domain if model is Domain else job

        async def execute(self, statement):
            if str(statement).startswith("DELETE"):
                # Both deletes must carry a domain predicate, never affect other sites.
                assert statement.compile().params == {"domain_id_1": 1}
                assert "domain_id" in str(statement)
                events.append(
                    "reset_boards" if statement.table.name == "board_source" else "reset_pages"
                )
            return SimpleNamespace(all=lambda: [], scalar_one_or_none=lambda: job)

        async def commit(self):
            pass

    async def reset(**kwargs):
        events.append("reset_rag")

    async def collect(ctx, **kwargs):
        assert not kwargs["manage_job"]
        assert ctx["full_url_limit"] == 2000
        events.append("boards")

    async def fetch(*args, **kwargs):
        events.append("bfs")
        return None

    monkeypatch.setattr(module, "start_job", AsyncMock())
    monkeypatch.setattr(module, "finish_job", AsyncMock())
    monkeypatch.setattr(module, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr("kspo_ingest.crawl.start_url.preflight_start", AsyncMock())
    monkeypatch.setattr(module, "discover_sitemap_urls", AsyncMock(return_value=[]))
    monkeypatch.setattr(module, "fetch_page", fetch)
    monkeypatch.setattr(board, "_run_board_refresh_impl", collect)
    redis = fakeredis.aioredis.FakeRedis()
    try:
        await module._enqueue_seeds_impl(
            {
                "session_factory": Session,
                "frontier": Frontier(redis),
                "storage_root": tmp_path,
                "sonar_client": SimpleNamespace(reset_site=reset),
                "sonar_namespace": "kspo",
            },
            job_id=1,
            domain_id=1,
        )
    finally:
        await redis.aclose()
    assert events == ["reset_rag", "reset_pages", "reset_boards", "bfs"]
    assert job.stats["termination_reason"] == "queue_exhausted"
