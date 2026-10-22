from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from kspo_ingest.crawl.board import build_page_url, next_board_page_url, page_param_for_host


@pytest.mark.parametrize("host", ["ksponco.or.kr", "www.ksponco.or.kr"])
def test_ksponco_cursor_and_actual_paging_controls(host):
    url = f"https://{host}/board.es?bid=0065&mid=a10503030000"
    param = page_param_for_host(host)
    assert param == "nPage"
    assert "nPage=2" in build_page_url(url, 2, param=param)
    html = '<a href="javascript:goPage(2);">2</a><a href="javascript:goPage(4);">Last</a>'
    assert next_board_page_url(html, url, 1, param=param).endswith("nPage=2")
    assert next_board_page_url(html, url, 4, param=param) is None
    href = '<a href="/board.es?bid=0065&mid=a10503030000&nPage=3&b_list_cnt=10">Next</a>'
    assert next_board_page_url(href, url, 1, param=param).endswith("nPage=3&b_list_cnt=10")


def setup_run(monkeypatch, *, count=1):
    from kspo_ingest.db.models import BoardSource, CrawlJob, Domain
    from kspo_ingest.tasks.pipeline import run_board_refresh as module

    sources = [
        SimpleNamespace(id=i + 1, list_url=f"https://x.kr/board.es?bid={i + 1}", newest_first=True)
        for i in range(count)
    ]
    job = CrawlJob(id=1, domain_id=1, job_type="full", stats={})
    domain = SimpleNamespace(host="x.kr", user_agent=None, rate_limit_rps=1, max_pages=100)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, ident):
            if model is Domain:
                return domain
            if model is BoardSource:
                return next(x for x in sources if x.id == ident)
            return job

        async def scalars(self, statement):
            return []

        async def execute(self, statement):
            return SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: list(sources)),
                all=lambda: [],
                scalar_one_or_none=lambda: job,
            )

        async def commit(self):
            pass

    async def verify(session, source, domain, **kwargs):
        return source.list_url

    monkeypatch.setattr("kspo_ingest.crawl.board_detect.revalidate_source", verify)
    monkeypatch.setattr(module, "is_cancelled", AsyncMock(return_value=False))
    fetch = AsyncMock(
        return_value=SimpleNamespace(
            http_status=200, raw_bytes=b"<main>No records</main>", content_type="text/html"
        )
    )
    ctx = {
        "session_factory": Session,
        "smart_fetcher": SimpleNamespace(fetch=fetch),
        "rate_limit": SimpleNamespace(acquire=AsyncMock()),
    }
    return module, ctx, sources, job, fetch


@pytest.mark.asyncio
async def test_idle_bfs_time_is_not_charged_to_shared_budget(monkeypatch):
    module, ctx, sources, job, fetch = setup_run(monkeypatch)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(module, "monotonic", lambda: clock.now)
    monkeypatch.setattr(module.settings, "board_total_max_seconds", 10)

    async def download(*args, **kwargs):
        clock.now += 2
        return SimpleNamespace(
            http_status=200, raw_bytes=b"<main>No records</main>", content_type="text/html"
        )

    fetch.side_effect = download
    await module._run_board_refresh_impl(ctx, job_id=1, domain_id=1, manage_job=False)
    assert ctx["board_time_budgets"][1]["used"] == 2
    clock.now += 3600  # The next board was discovered an hour later by ordinary BFS.
    sources.append(SimpleNamespace(id=2, list_url="https://x.kr/board.es?bid=2", newest_first=True))
    await module._run_board_refresh_impl(ctx, job_id=1, domain_id=1, manage_job=False)
    assert fetch.await_count == 2
    assert ctx["board_time_budgets"][1]["used"] == 4
    assert job.stats["board_outcomes"]["2"]["reason"] == "empty_list"
    assert not job.stats.get("board_deferred")


@pytest.mark.asyncio
async def test_exhausted_total_budget_defers_without_per_source_errors(monkeypatch):
    module, ctx, sources, job, fetch = setup_run(monkeypatch, count=3)
    monkeypatch.setattr(module.settings, "board_total_max_seconds", 10)
    ctx["board_time_budgets"] = {1: {"used": 10}}
    await module._run_board_refresh_impl(ctx, job_id=1, domain_id=1, manage_job=False)
    fetch.assert_not_awaited()
    assert not job.stats.get("board_outcomes")
    assert len(job.stats["board_deferred"]) == 3
    assert job.stats["board_budget_exhausted"] and job.stats["collection_partial"]
    assert not ctx["full_board_sources_done"]
    # A source discovered later must also be reported, without trying it with 1ms timeout.
    sources.append(SimpleNamespace(id=4, list_url="https://x.kr/board.es?bid=4", newest_first=True))
    await module._run_board_refresh_impl(ctx, job_id=1, domain_id=1, manage_job=False)
    assert len(job.stats["board_deferred"]) == 4
    fetch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("total_limited", [True, False])
async def test_validation_timeout_reports_phase_and_correct_budget(monkeypatch, total_limited):
    import asyncio

    module, ctx, sources, job, fetch = setup_run(monkeypatch, count=2)
    monkeypatch.setattr(module.settings, "board_total_max_seconds", 0.02 if total_limited else 10)
    monkeypatch.setattr(module.settings, "board_max_seconds", 1 if total_limited else 0.01)

    async def slow_verify(*args, **kwargs):
        await asyncio.sleep(0.05)

    monkeypatch.setattr("kspo_ingest.crawl.board_detect.revalidate_source", slow_verify)
    await module._run_board_refresh_impl(ctx, job_id=1, domain_id=1, manage_job=False)
    outcome = job.stats["board_outcomes"]["1"]
    assert outcome["page"] == 0
    assert outcome["reason"] == ("total_time_limit" if total_limited else "time_limit")
    if total_limited:
        assert len(job.stats["board_outcomes"]) == 1
        assert len(job.stats["board_deferred"]) == 2
    else:
        assert not job.stats.get("board_deferred")
    fetch.assert_not_awaited()


def test_detail_navigation_cursor_is_not_a_paging_control():
    url = "https://ksponco.or.kr/board.es?bid=0065"
    html = '<a href="/board.es?bid=0065&act=view&list_no=1&nPage=1">Article</a>'
    assert next_board_page_url(html, url, 1, param="nPage").endswith("nPage=2")
