from __future__ import annotations

import asyncio
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from kspo_ingest.settings import Settings
from kspo_ingest.tasks.pipeline import parallel as mod


@pytest.fixture
def runtime(monkeypatch):
    counts = defaultdict(lambda: defaultdict(int))
    pages = defaultdict(lambda: SimpleNamespace(storage_paths={"processing_pending": True}))
    state = {"cancelled": False}

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, model, ident):
            return pages[ident]

        async def commit(self):
            pass

    async def bump(session, job_id, **delta):
        for key, value in delta.items():
            counts[job_id][key] += value

    async def cancelled(*args):
        return state["cancelled"]

    monkeypatch.setattr(mod, "bump_stats", bump)
    monkeypatch.setattr(mod, "is_cancelled", cancelled)
    monkeypatch.setattr(mod, "mark_error", AsyncMock())
    return (
        {"session_factory": Session, "postprocess_slots": asyncio.BoundedSemaphore(10)},
        counts,
        pages,
        state,
    )


@pytest.mark.asyncio
async def test_two_producers_share_global_ten_limit_and_no_lost_work(runtime):
    ctx, counts, _, _ = runtime
    active = peak = finished = 0

    async def work():
        nonlocal active, peak, finished
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        finished += 1

    async def producer(job_id):
        async with mod.processing_scope(ctx, job_id) as run:
            for pid in range(25):
                await mod.submit_postprocessing(run, job_id, pid, work)
            await mod.drain_processing(run)
            assert counts[job_id]["processing_completed"] == 25

    await asyncio.gather(producer(1), producer(2))
    assert finished == 50
    assert peak == 10
    assert all(c["processing_pending"] == c["processing_running"] == 0 for c in counts.values())


@pytest.mark.asyncio
async def test_first_item_runs_immediately_and_scope_waits(runtime):
    ctx, counts, _, _ = runtime
    started, release = asyncio.Event(), asyncio.Event()

    async def work():
        started.set()
        await release.wait()

    async def producer():
        async with mod.processing_scope(ctx, 1) as run:
            await mod.submit_postprocessing(run, 1, 10, work)

    task = asyncio.create_task(producer())
    await started.wait()
    assert not task.done()
    release.set()
    await task
    assert counts[1]["processing_completed"] == 1


@pytest.mark.asyncio
async def test_backpressure_and_duplicate_page(runtime):
    ctx, _, _, _ = runtime
    release = asyncio.Event()
    work = AsyncMock(side_effect=release.wait)
    pool = mod.PostprocessPool(ctx, 1, ctx["postprocess_slots"], 2)
    await pool.submit(1, work)
    await pool.submit(1, work)
    await pool.submit(2, work)
    third = asyncio.create_task(pool.submit(3, work))
    await asyncio.sleep(0)
    assert not third.done()
    assert len(pool.tasks) == 2
    release.set()
    await third
    await pool.drain()
    assert work.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("counted", [True, False])
async def test_failed_page_is_reported_once_and_other_pages_continue(runtime, counted):
    ctx, counts, pages, _ = runtime

    async def bad():
        raise mod.PublicationError("failed", counted=counted)

    good = AsyncMock()
    async with mod.processing_scope(ctx, 1) as run:
        await mod.submit_postprocessing(run, 1, 1, bad)
        await mod.submit_postprocessing(run, 1, 2, good)
    assert counts[1]["processing_failed"] == 1
    assert counts[1]["errors"] == int(not counted)
    assert counts[1]["processing_completed"] == 1
    assert pages[1].storage_paths["processing_pending"] is True
    assert pages[2].storage_paths["processing_pending"] is False
    assert counts[1]["processing_pending"] == 0


@pytest.mark.asyncio
async def test_parent_failure_cancels_and_joins_child_tasks(runtime):
    ctx, counts, pages, _ = runtime
    started, stopped = asyncio.Event(), asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    with pytest.raises(ValueError):
        async with mod.processing_scope(ctx, 1) as run:
            await mod.submit_postprocessing(run, 1, 1, work)
            await started.wait()
            raise ValueError("producer failed")
    assert stopped.is_set()
    assert counts[1]["processing_pending"] == counts[1]["processing_running"] == 0
    assert pages[1].storage_paths["processing_pending"] is True


@pytest.mark.asyncio
async def test_cancelled_job_never_starts_waiting_llm(runtime):
    ctx, counts, _, state = runtime
    state["cancelled"] = True
    work = AsyncMock()
    async with mod.processing_scope(ctx, 1) as run:
        await mod.submit_postprocessing(run, 1, 1, work)
    work.assert_not_awaited()
    assert counts[1]["processing_pending"] == 0


@pytest.mark.asyncio
async def test_cancel_during_llm_keeps_retry_checkpoint(runtime):
    ctx, counts, pages, state = runtime

    async def work():
        state["cancelled"] = True

    async with mod.processing_scope(ctx, 1) as run:
        await mod.submit_postprocessing(run, 1, 1, work)
    assert pages[1].storage_paths["processing_pending"] is True
    assert counts[1]["processing_completed"] == 0


@pytest.mark.asyncio
async def test_metrics_failure_is_not_silently_discarded(runtime, monkeypatch):
    ctx, _, _, _ = runtime
    pool = mod.PostprocessPool(ctx, 1, ctx["postprocess_slots"], 1)

    async def broken():
        raise RuntimeError("db down")

    pool.tasks.add(asyncio.create_task(broken()))
    with pytest.raises(RuntimeError, match="db down"):
        await pool.submit(2, AsyncMock())


@pytest.mark.asyncio
async def test_direct_call_still_finishes_before_return(runtime):
    ctx, _, _, _ = runtime
    work = AsyncMock()
    await mod.submit_postprocessing(ctx, 1, 1, work)
    work.assert_awaited_once()


def test_setting_enforces_hard_ten_limit():
    for value in [0, 11]:
        with pytest.raises(ValidationError):
            Settings(postprocess_concurrency=value)
    assert Settings(postprocess_concurrency=10).postprocess_concurrency == 10


@pytest.mark.asyncio
async def test_local_direct_indexing_uses_the_shared_ten_slot_pool(runtime, monkeypatch):
    from kspo_ingest.tasks.pipeline import chunk_and_index as index_module
    from kspo_ingest.tasks.pipeline.push_to_sonar import push_to_sonar

    ctx, counts, _, _ = runtime
    ctx["local_direct_indexing"] = True
    active = peak = finished = 0

    async def index(*args, **kwargs):
        nonlocal active, peak, finished
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        finished += 1
        return 2

    monkeypatch.setattr(index_module, "chunk_and_index", index)
    async with mod.processing_scope(ctx, 1) as run:
        for pid in range(30):

            async def work(page_id=pid):
                assert (
                    await push_to_sonar(
                        run,
                        job_id=1,
                        page_id=page_id,
                        refined_text="local text",
                        summary="summary",
                        keywords=[],
                    )
                    == 1
                )

            await mod.submit_postprocessing(run, 1, pid, work)
    assert peak == 10
    assert finished == counts[1]["processing_completed"] == 30
    assert counts[1]["processing_pending"] == counts[1]["processing_running"] == 0
