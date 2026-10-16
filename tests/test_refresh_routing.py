from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.api.routers import jobs
from kspo_ingest.api.schemas.job import RefreshUrlRequest
from kspo_ingest.tasks.pipeline import refresh_url


@pytest.mark.asyncio
async def test_refresh_resolves_actual_host_before_page_lookup(monkeypatch):
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: SimpleNamespace(id=9, is_active=True))
    )
    session.commit = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda row: setattr(row, "id", 1331))
    page_lookup = AsyncMock(return_value=SimpleNamespace(id=42, domain_id=9))
    monkeypatch.setattr(jobs, "get_or_create_page", page_lookup)
    pool = SimpleNamespace(enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="arq-test")))
    monkeypatch.setattr(jobs, "_get_pool", AsyncMock(return_value=pool))
    result = await jobs.trigger_refresh_url(
        RefreshUrlRequest(url="https://nfa.kspo.or.kr/main.kspo", force=True),
        s=session,
        _admin="admin",
    )
    assert result.page_id == 42
    assert session.execute.await_count == 1
    assert "domains.host" in str(session.execute.call_args.args[0])
    assert page_lookup.call_args.kwargs["domain_id"] == 9
    job = session.add.call_args.args[0]
    assert job.domain_id == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stats,expected",
    [
        ({"errors": 1, "fetched": 0}, "FAILED"),
        ({"errors": 1, "fetched": 1}, "FAILED"),
        ({"errors": 0, "skipped": 1}, "SUCCESS"),
        ({"errors": 0, "dropped": 1}, "SUCCESS"),
    ],
)
async def test_refresh_terminal_status(monkeypatch, stats, expected):
    session = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(stats=stats)))
    finish = AsyncMock()
    monkeypatch.setattr(refresh_url, "finish_job", finish)
    await refresh_url._finish_refresh(session, 1)
    assert finish.call_args.kwargs["status"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("example.com", "https://example.com/"),
        ("https://example.com/info/list?page=2", "https://example.com/info/list?page=2"),
        ("https://nfa.kspo.or.kr/intro/intro.kspo", "https://nfa.kspo.or.kr/intro/intro.kspo"),
    ],
)
async def test_crawl_input_always_overrides_saved_entry(monkeypatch, raw, expected):
    from datetime import UTC, datetime

    from kspo_ingest.api.schemas.job import JobOut

    session = MagicMock()
    domain = SimpleNamespace(id=9, is_active=True, start_url="https://example.com/old")
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: domain))
    trigger = AsyncMock(
        return_value=JobOut(
            id=1,
            domain_id=9,
            job_type="full",
            status="PENDING",
            triggered_by="admin",
            created_at=datetime.now(UTC),
            seed_urls=[expected],
        )
    )
    monkeypatch.setattr(jobs, "_trigger_job", trigger)
    await jobs.trigger_crawl_by_host(jobs.CrawlRequest(input=raw), s=session, _admin="admin")
    assert trigger.call_args.kwargs["seed_urls"] == [expected]
