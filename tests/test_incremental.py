"""run_incremental + clean_page skip + refine purge 통합 단위 테스트.

실제 OpenAI / Qdrant 호출 없이 monkeypatch로 stub. fetch_page도 mock하여
HTTP 호출은 발생하지 않는다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from kspo_ingest.tasks.pipeline import refine_page as refine_mod
from kspo_ingest.tasks.pipeline import run_incremental as inc_mod


class FakeDomain:
    def __init__(self, domain_id=1, host="example.com", scheme="https", is_active=True):
        self.id = domain_id
        self.host = host
        self.scheme = scheme
        self.is_active = is_active


def _make_session_factory(domain=None, urls=()):
    """run_incremental 진입에서 session_factory를 한 번 호출하여 domain 조회 + URL 수집."""
    s = MagicMock()
    s.get = AsyncMock(return_value=domain)

    rows_result = MagicMock()
    rows_result.all = MagicMock(return_value=[(u,) for u in urls])
    s.execute = AsyncMock(return_value=rows_result)
    s.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=s)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.mark.asyncio
async def test_run_incremental_iterates_existing_pages_plus_root(monkeypatch):
    domain = FakeDomain(host="example.com", scheme="https")
    factory = _make_session_factory(
        domain=domain, urls=["https://example.com/a", "https://example.com/b"]
    )

    calls = []

    async def fake_process(ctx, *, job_id, domain_id, url):
        calls.append(url)

    monkeypatch.setattr(inc_mod, "_process_one", fake_process)
    monkeypatch.setattr(inc_mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(inc_mod, "start_job", AsyncMock())
    monkeypatch.setattr(inc_mod, "finish_job", AsyncMock())
    monkeypatch.setattr(inc_mod, "bump_stats", AsyncMock())

    ctx = {"session_factory": factory}
    await inc_mod.run_incremental(ctx, job_id=1, domain_id=1)

    # 기존 2개 + root 1개
    assert calls == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/",
    ]
    inc_mod.finish_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_incremental_root_already_in_pages_no_duplicate(monkeypatch):
    domain = FakeDomain(host="example.com", scheme="https")
    factory = _make_session_factory(domain=domain, urls=["https://example.com/"])

    calls = []

    async def fake_process(ctx, *, job_id, domain_id, url):
        calls.append(url)

    monkeypatch.setattr(inc_mod, "_process_one", fake_process)
    monkeypatch.setattr(inc_mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(inc_mod, "start_job", AsyncMock())
    monkeypatch.setattr(inc_mod, "finish_job", AsyncMock())
    monkeypatch.setattr(inc_mod, "bump_stats", AsyncMock())

    ctx = {"session_factory": factory}
    await inc_mod.run_incremental(ctx, job_id=1, domain_id=1)

    assert calls == ["https://example.com/"]


@pytest.mark.asyncio
async def test_run_incremental_inactive_domain_fails(monkeypatch):
    domain = FakeDomain(is_active=False)
    factory = _make_session_factory(domain=domain, urls=[])
    finish = AsyncMock()
    monkeypatch.setattr(inc_mod, "finish_job", finish)
    monkeypatch.setattr(inc_mod, "_process_one", AsyncMock())

    ctx = {"session_factory": factory}
    await inc_mod.run_incremental(ctx, job_id=1, domain_id=1)

    finish.assert_awaited_once()
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "FAILED"


@pytest.mark.asyncio
async def test_run_incremental_no_domain_fails(monkeypatch):
    factory = _make_session_factory(domain=None)
    finish = AsyncMock()
    monkeypatch.setattr(inc_mod, "finish_job", finish)

    ctx = {"session_factory": factory}
    await inc_mod.run_incremental(ctx, job_id=1, domain_id=999)

    args, kwargs = finish.call_args
    assert kwargs.get("status") == "FAILED"


@pytest.mark.asyncio
async def test_run_incremental_cancellation_short_circuits(monkeypatch):
    domain = FakeDomain()
    factory = _make_session_factory(domain=domain, urls=["https://example.com/a"])

    calls = []

    async def fake_process(*a, **kw):
        calls.append(kw.get("url"))

    monkeypatch.setattr(inc_mod, "_process_one", fake_process)
    monkeypatch.setattr(inc_mod, "is_cancelled", AsyncMock(return_value=True))
    monkeypatch.setattr(inc_mod, "start_job", AsyncMock())
    finish = AsyncMock()
    monkeypatch.setattr(inc_mod, "finish_job", finish)
    monkeypatch.setattr(inc_mod, "bump_stats", AsyncMock())

    ctx = {"session_factory": factory}
    await inc_mod.run_incremental(ctx, job_id=1, domain_id=1)

    assert calls == []  # cancelled 즉시 종료
    args, kwargs = finish.call_args
    assert kwargs.get("status") == "CANCELLED"


@pytest.mark.asyncio
async def test_process_one_skips_chunk_when_clean_returns_skipped(monkeypatch):
    monkeypatch.setattr(inc_mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        inc_mod, "clean_page", AsyncMock(return_value={"skipped": True, "page_id": 10})
    )
    refine_called = AsyncMock()
    chunk_called = AsyncMock()
    monkeypatch.setattr(inc_mod, "extract_links", AsyncMock())
    monkeypatch.setattr(inc_mod, "refine_page", refine_called)
    monkeypatch.setattr(inc_mod, "chunk_and_index", chunk_called)

    await inc_mod._process_one({}, job_id=1, domain_id=1, url="https://x/")

    refine_called.assert_not_awaited()
    chunk_called.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_one_runs_full_chain_when_changed(monkeypatch):
    monkeypatch.setattr(inc_mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        inc_mod,
        "clean_page",
        AsyncMock(
            return_value={
                "skipped": False,
                "page_id": 10,
                "title": "T",
                "body_text": "본문",
                "content_hash": "h",
            }
        ),
    )
    monkeypatch.setattr(inc_mod, "extract_links", AsyncMock())
    monkeypatch.setattr(
        inc_mod,
        "refine_page",
        AsyncMock(
            return_value={
                "page_id": 10,
                "refined": {
                    "refined_text": "정제본문",
                    "summary": "요약",
                    "keywords": ["k1"],
                    "is_meaningful": True,
                },
            }
        ),
    )
    chunk_called = AsyncMock()
    monkeypatch.setattr(inc_mod, "chunk_and_index", chunk_called)

    await inc_mod._process_one({}, job_id=1, domain_id=1, url="https://x/")

    chunk_called.assert_awaited_once()
    args, kwargs = chunk_called.call_args
    assert kwargs["refined_text"] == "정제본문"
    assert kwargs["summary"] == "요약"


@pytest.mark.asyncio
async def test_process_one_fetch_none_short_circuits(monkeypatch):
    monkeypatch.setattr(inc_mod, "fetch_page", AsyncMock(return_value=None))
    clean = AsyncMock()
    monkeypatch.setattr(inc_mod, "clean_page", clean)
    await inc_mod._process_one({}, job_id=1, domain_id=1, url="https://x/")
    clean.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_one_refine_drop_short_circuits(monkeypatch):
    monkeypatch.setattr(inc_mod, "fetch_page", AsyncMock(return_value=10))
    monkeypatch.setattr(
        inc_mod,
        "clean_page",
        AsyncMock(
            return_value={
                "skipped": False,
                "page_id": 10,
                "title": "T",
                "body_text": "본문",
                "content_hash": "h",
            }
        ),
    )
    monkeypatch.setattr(inc_mod, "extract_links", AsyncMock())
    monkeypatch.setattr(inc_mod, "refine_page", AsyncMock(return_value=None))
    chunk_called = AsyncMock()
    monkeypatch.setattr(inc_mod, "chunk_and_index", chunk_called)

    await inc_mod._process_one({}, job_id=1, domain_id=1, url="https://x/")
    chunk_called.assert_not_awaited()


@pytest.mark.asyncio
async def test_refine_purge_existing_chunks_calls_qdrant_and_pg(monkeypatch):
    point_ids = [UUID("00000000-0000-0000-0000-000000000001")]
    s = MagicMock()
    rows = MagicMock()
    rows.all = MagicMock(return_value=[(101, point_ids[0])])
    s.execute = AsyncMock(return_value=rows)
    s.commit = AsyncMock()

    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(refine_mod, "QdrantDirectAdapter", lambda: fake_adapter)

    n = await refine_mod._purge_existing_chunks(s, page_id=10)
    assert n == 1
    fake_adapter.delete_by_ids.assert_awaited_once_with(point_ids)
    # PG DELETE도 실행됨
    assert s.execute.await_count == 2  # 1: SELECT, 2: DELETE


@pytest.mark.asyncio
async def test_refine_purge_no_chunks_is_noop(monkeypatch):
    s = MagicMock()
    rows = MagicMock()
    rows.all = MagicMock(return_value=[])
    s.execute = AsyncMock(return_value=rows)
    s.commit = AsyncMock()
    monkeypatch.setattr(
        refine_mod, "QdrantDirectAdapter", lambda: MagicMock(delete_by_ids=AsyncMock())
    )
    n = await refine_mod._purge_existing_chunks(s, page_id=10)
    assert n == 0
