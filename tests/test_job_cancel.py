"""Job cancel 동작 단위 테스트.

API 측은 `cancel_job` 엔드포인트의 status 검증 로직을 직접 import하여 호출.
worker 측은 `is_cancelled` SELECT가 CANCELLED 상태를 정확히 감지하는지 mock으로 확인.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from kspo_ingest.api.routers import jobs as jobs_router
from kspo_ingest.tasks import jobs as jobs_mod


class FakeCrawlJob:
    def __init__(self, job_id=1, status="PENDING"):
        self.id = job_id
        self.status = status
        self.finished_at = None


def _make_session(*, job=None):
    s = MagicMock()
    s.get = AsyncMock(return_value=job)
    s.commit = AsyncMock()
    return s


# ---------- API cancel_job ----------
@pytest.mark.asyncio
async def test_cancel_pending_job_marks_cancelled():
    job = FakeCrawlJob(status="PENDING")
    s = _make_session(job=job)

    response = await jobs_router.cancel_job(id=1, s=s, _admin="admin")

    assert response.status_code == 204
    assert job.status == "CANCELLED"
    assert isinstance(job.finished_at, datetime)
    assert job.finished_at.tzinfo == UTC
    s.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_running_job_marks_cancelled():
    job = FakeCrawlJob(status="RUNNING")
    s = _make_session(job=job)

    response = await jobs_router.cancel_job(id=1, s=s, _admin="admin")
    assert response.status_code == 204
    assert job.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_already_success_returns_409():
    job = FakeCrawlJob(status="SUCCESS")
    s = _make_session(job=job)

    with pytest.raises(HTTPException) as exc_info:
        await jobs_router.cancel_job(id=1, s=s, _admin="admin")
    assert exc_info.value.status_code == 409
    assert "SUCCESS" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_cancel_already_failed_returns_409():
    job = FakeCrawlJob(status="FAILED")
    s = _make_session(job=job)

    with pytest.raises(HTTPException) as exc_info:
        await jobs_router.cancel_job(id=1, s=s, _admin="admin")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_already_cancelled_returns_409():
    job = FakeCrawlJob(status="CANCELLED")
    s = _make_session(job=job)
    with pytest.raises(HTTPException) as exc_info:
        await jobs_router.cancel_job(id=1, s=s, _admin="admin")
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_cancel_nonexistent_job_returns_404():
    s = _make_session(job=None)
    with pytest.raises(HTTPException) as exc_info:
        await jobs_router.cancel_job(id=999, s=s, _admin="admin")
    assert exc_info.value.status_code == 404


# ---------- worker is_cancelled ----------
@pytest.mark.asyncio
async def test_is_cancelled_true_for_cancelled_status():
    s = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value="CANCELLED")
    s.execute = AsyncMock(return_value=result)

    assert await jobs_mod.is_cancelled(s, 1) is True


@pytest.mark.asyncio
async def test_is_cancelled_false_for_running_status():
    s = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value="RUNNING")
    s.execute = AsyncMock(return_value=result)

    assert await jobs_mod.is_cancelled(s, 1) is False


@pytest.mark.asyncio
async def test_is_cancelled_false_for_missing_job():
    s = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    s.execute = AsyncMock(return_value=result)

    assert await jobs_mod.is_cancelled(s, 999) is False
