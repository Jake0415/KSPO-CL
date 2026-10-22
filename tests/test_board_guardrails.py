from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.board_identity import board_key, is_board_owned_link
from kspo_ingest.crawl.board_validation import entry_url
from kspo_ingest.crawl.loop_guard import list_family, list_signature
from kspo_ingest.crawl.url_normalize import normalize_url


@pytest.mark.parametrize(
    "entry,detail",
    [
        ("https://x.kr/board.es?bid=1", "https://x.kr/board.es?bid=1&act=view&list_no=2&nPage=74"),
        ("https://x.kr/gallery.es?bid=1", "https://x.kr/gallery.es?bid=1&act=view&list_no=2"),
        (
            "https://x.kr/bbsList.do?boardId=1",
            "https://x.kr/bbsView.do?boardId=1&conSeq=2&pageNo=4",
        ),
        ("https://x.kr/selectNoticeList.kspo", "https://x.kr/selectNoticeView.kspo?nttId=2"),
    ],
)
def test_shared_identity(entry, detail):
    assert is_board_owned_link(detail, confirmed_list_urls={entry})
    assert list_family(entry)
    assert list_family(detail) is None
    assert board_key(entry) == board_key(detail)


def test_board_identity_preserves_other_boards_and_search():
    entry = "https://x.kr/board.es?bid=1"
    assert not is_board_owned_link("https://x.kr/board.es?bid=2", confirmed_list_urls={entry})
    assert board_key(entry + "&category=A") != board_key(entry + "&category=B")
    assert board_key(entry + "&keyword=A") != board_key(entry + "&keyword=B")
    assert board_key("https://x.kr/about") is None


def test_detail_cannot_be_registered_as_list():
    assert entry_url("https://x.kr/board.es?act=view&list_no=1&bid=1", "x.kr") is None


def test_card_layout_notice_icon_is_recognized():
    from kspo_ingest.crawl.board import extract_board_items

    html = """<ul><li class="list_li"><a href="/board.es?act=view&list_no=1">
      <strong><i class="icon_notice">Notice</i>title</strong>
      <span class="date">2026-10-07</span></a></li></ul>"""
    items = extract_board_items(html, base_url="https://x.kr/board.es")
    assert len(items) == 1
    assert items[0].is_notice


def test_escaped_menu_variants_are_one_board():
    plain = "https://x.kr/bbsList.do?boardId=1&topMenuSeq=2"
    escaped = "https://x.kr/bbsList.do?boardId=1&amp;topMenuSeq=3"
    assert entry_url(plain, "x.kr") == entry_url(escaped, "x.kr")
    assert normalize_url(plain)[1] == normalize_url(escaped)[1]


def test_esafer_repeated_list_detected_across_cursors():
    entry = "https://x.kr/board.es?bid=1"
    detail = entry + "&act=view&list_no=3"
    assert list_signature(entry + "&nPage=1", [detail + "&nPage=1"]) == list_signature(
        entry + "&nPage=2", [detail + "&nPage=2"]
    )
    assert list_signature(entry, [detail]) is not None


@pytest.mark.asyncio
async def test_partial_board_finishes_as_success_with_warning(monkeypatch):
    from kspo_ingest.tasks import jobs

    finish = AsyncMock()
    monkeypatch.setattr(jobs, "finish_job", finish)
    session = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(stats={"collection_partial": True}))
    )
    await jobs.finish_crawl_job(session, 1)
    assert finish.call_args.kwargs["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_discovery_and_board_admission_share_atomic_budget():
    import asyncio

    import fakeredis.aioredis

    from kspo_ingest.crawl.frontier import Frontier

    redis = fakeredis.aioredis.FakeRedis()
    try:
        frontier = Frontier(redis)
        await redis.set("crawl_limit:1", 2)
        admitted = await asyncio.gather(
            *(frontier.reserve_discovery(1, f"https://x.kr/{n}", limit=2) for n in range(10))
        )
        assert sum(admitted) == 2
        assert await redis.scard("admitted:1") == 2
        assert await frontier.enqueue(1, "https://x.kr/0", 0)
        assert not await frontier.admit_direct(1, "https://x.kr/board.es?bid=1", limit=2)
        assert await redis.get("url_limit:1") == b"1"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_db_insert_is_bounded_before_queueing():
    import fakeredis.aioredis

    from kspo_ingest.tasks.pipeline.extract_links import _upsert_discovered_pages

    inserted = []

    async def execute(statement):
        if str(statement).startswith("SELECT"):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        inserted.append(statement.compile().params)
        return SimpleNamespace(rowcount=2)

    redis = fakeredis.aioredis.FakeRedis()
    try:
        await _upsert_discovered_pages(
            SimpleNamespace(execute=execute, commit=AsyncMock()),
            page=SimpleNamespace(url="https://x.kr/", domain_id=1, depth=0, storage_paths={}),
            domain=SimpleNamespace(id=1, host="x.kr", max_depth=10, max_pages=2),
            html="".join(f'<a href="/{n}">link</a>' for n in range(10)),
            redis=redis,
            job_id=1,
        )
        assert len(inserted) == 1
        assert len([k for k in inserted[0] if k.startswith("url_hash_m")]) == 2
        assert await redis.scard("admitted:1") == 2
    finally:
        await redis.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,reason,partial",
    [
        ("page_cap", "page_limit", True),
        ("empty", "empty_list", False),
        ("article_cap", "article_limit", True),
        ("repeated", "repeated_list", False),
        ("time_cap", "time_limit", True),
        ("date", "date_boundary", False),
    ],
)
async def test_board_exit_records_reason_and_partial(monkeypatch, scenario, reason, partial):
    import asyncio
    from urllib.parse import parse_qs, urlsplit

    from kspo_ingest.db.models import BoardSource, CrawlJob, Domain
    from kspo_ingest.tasks.pipeline import run_board_refresh as module

    source = SimpleNamespace(id=1, list_url="https://x.kr/board.es?bid=1", newest_first=True)
    domain = SimpleNamespace(host="x.kr", user_agent=None, rate_limit_rps=1, max_pages=100)
    job = CrawlJob(id=1, domain_id=1, job_type="full", stats={})

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, ident):
            return domain if model is Domain else source if model is BoardSource else job

        async def execute(self, statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [source]),
                all=lambda: [],
                scalar_one_or_none=lambda: job,
            )

        async def commit(self):
            pass

    async def fetch(url, **kwargs):
        if scenario == "time_cap":
            await asyncio.sleep(0.05)
        if scenario == "empty":
            return SimpleNamespace(
                http_status=200,
                raw_bytes=(
                    b'<main><p>No records</p><li><a href="javascript:void(0)" '
                    b'onclick="fnSearch(1)">1</a></li></main>'
                ),
                content_type="text/html",
            )
        page = int(parse_qs(urlsplit(url).query)["pageIndex"][0])
        number = 1 if scenario == "repeated" else page
        date = "2020-01-01" if scenario == "date" else datetime.now(UTC).strftime("%Y-%m-%d")
        html = "".join(
            f'<tr><td><a href="/board.es?bid=1&act=view&list_no={number * 10 + n}'
            f'&nPage={page}">a</a></td><td class="date">{date}</td></tr>'
            for n in range(2)
        )
        return SimpleNamespace(
            http_status=200, raw_bytes=f"<table>{html}</table>".encode(), content_type="text/html"
        )

    monkeypatch.setattr(
        "kspo_ingest.crawl.board_detect.revalidate_source", AsyncMock(return_value=source.list_url)
    )
    monkeypatch.setattr(module, "is_cancelled", AsyncMock(return_value=False))
    process = AsyncMock()
    monkeypatch.setattr(module, "process_board_page", process)
    if scenario == "article_cap":
        monkeypatch.setattr(module.settings, "board_max_articles", 1)
    if scenario == "time_cap":
        monkeypatch.setattr(module.settings, "board_max_seconds", 0.01)
    await module._run_board_refresh_impl(
        {
            "session_factory": Session,
            "smart_fetcher": SimpleNamespace(fetch=fetch),
            "rate_limit": SimpleNamespace(acquire=AsyncMock()),
        },
        job_id=1,
        domain_id=1,
        manage_job=False,
        max_pages=2 if scenario == "page_cap" else 5,
    )
    outcome = job.stats["board_outcomes"]["1"]
    assert outcome["reason"] == reason
    assert outcome["partial"] is partial
    assert job.stats["collection_partial"] is partial
    if scenario == "repeated":
        assert process.await_count == 2
