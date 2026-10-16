"""job_guard: guarantee a terminal job status on failure (audit 2026-07-10)."""
from __future__ import annotations

import contextlib

import pytest

import kspo_ingest.tasks.jobs as jobs


class _FakeSessionFactory:
    def __call__(self):
        @contextlib.asynccontextmanager
        async def _cm():
            yield object()
        return _cm()


async def test_job_guard_marks_failed_and_reraises(monkeypatch):
    calls = []

    async def fake_finish(s, job_id, *, status, error=None):
        calls.append((job_id, status, error))

    monkeypatch.setattr(jobs, "finish_job", fake_finish)

    with pytest.raises(ValueError):
        async with jobs.job_guard(_FakeSessionFactory(), 42):
            raise ValueError("boom")

    assert calls == [(42, "FAILED", "boom")]


async def test_job_guard_noop_on_success(monkeypatch):
    calls = []

    async def fake_finish(s, job_id, *, status, error=None):
        calls.append((job_id, status, error))

    monkeypatch.setattr(jobs, "finish_job", fake_finish)

    async with jobs.job_guard(_FakeSessionFactory(), 7):
        pass  # normal completion — guard must NOT touch status

    assert calls == []


async def test_job_guard_marks_failed_on_cancellation(monkeypatch):
    """ARQ job_timeout raises CancelledError (BaseException) — must still FAILED."""
    calls = []

    async def fake_finish(s, job_id, *, status, error=None):
        calls.append((job_id, status))

    monkeypatch.setattr(jobs, "finish_job", fake_finish)

    import asyncio
    with pytest.raises(asyncio.CancelledError):
        async with jobs.job_guard(_FakeSessionFactory(), 99):
            raise asyncio.CancelledError()

    assert calls == [(99, "FAILED")]
