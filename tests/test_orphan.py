"""orphan.py 단위 테스트 — handle_404 + handle_domain_deactivation.

Qdrant 호출은 모두 mock. PG는 session.get / session.execute / session.commit를 stub.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from kspo_ingest.tasks.pipeline import orphan as mod


class FakePage:
    def __init__(self, page_id=1, error_count=0):
        self.id = page_id
        self.error_count = error_count
        self.last_http_status = None
        self.last_fetched_at = None
        self.status = "INDEXED"


class FakeDomain:
    def __init__(self, domain_id=1, host="example.com"):
        self.id = domain_id
        self.host = host


def _make_session(*, page=None, point_id_rows=()):
    s = MagicMock()
    s.get = AsyncMock(return_value=page)
    s.commit = AsyncMock()

    rows_result = MagicMock()
    rows_result.all = MagicMock(return_value=[(pid,) for pid in point_id_rows])
    s.execute = AsyncMock(return_value=rows_result)
    return s


@pytest.mark.asyncio
async def test_handle_404_below_threshold_only_increments(monkeypatch):
    page = FakePage(error_count=0)
    s = _make_session(page=page)
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=1)

    assert removed is False
    assert page.error_count == 1
    assert page.status == "INDEXED"  # 변동 없음
    fake_adapter.delete_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_404_at_threshold_minus_one_still_below(monkeypatch):
    page = FakePage(error_count=1)  # → 2 (still <3)
    s = _make_session(page=page)
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=1)

    assert removed is False
    assert page.error_count == 2
    assert page.status == "INDEXED"
    fake_adapter.delete_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_404_at_threshold_marks_removed_and_deletes_qdrant(monkeypatch):
    page = FakePage(error_count=2)  # → 3 (>= threshold)
    point_ids = [UUID("00000000-0000-0000-0000-000000000001"),
                 UUID("00000000-0000-0000-0000-000000000002")]
    s = _make_session(page=page, point_id_rows=point_ids)
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=1)

    assert removed is True
    assert page.error_count == 3
    assert page.status == "REMOVED"
    fake_adapter.delete_by_ids.assert_awaited_once_with(point_ids)


@pytest.mark.asyncio
async def test_handle_404_no_qdrant_chunks_still_marks_removed(monkeypatch):
    page = FakePage(error_count=2)
    s = _make_session(page=page, point_id_rows=())
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=1)

    assert removed is True
    assert page.status == "REMOVED"
    fake_adapter.delete_by_ids.assert_not_awaited()  # 청크 없으면 호출 X


@pytest.mark.asyncio
async def test_handle_404_qdrant_failure_does_not_block_removal(monkeypatch):
    page = FakePage(error_count=2)
    point_ids = [UUID("00000000-0000-0000-0000-000000000001")]
    s = _make_session(page=page, point_id_rows=point_ids)
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock(side_effect=RuntimeError("network down"))
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=1)
    assert removed is True
    assert page.status == "REMOVED"  # PG는 정리 완료


@pytest.mark.asyncio
async def test_handle_404_no_page_returns_false(monkeypatch):
    s = _make_session(page=None)
    fake_adapter = MagicMock()
    fake_adapter.delete_by_ids = AsyncMock()
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    removed = await mod.handle_404(s, page_id=999)
    assert removed is False
    fake_adapter.delete_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_domain_deactivation_calls_qdrant_and_marks_pages(monkeypatch):
    domain = FakeDomain(domain_id=1, host="example.com")
    s = MagicMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()

    fake_adapter = MagicMock()
    fake_adapter.delete_by_domain = AsyncMock(return_value=12)
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    deleted = await mod.handle_domain_deactivation(s, domain=domain)

    assert deleted == 12
    fake_adapter.delete_by_domain.assert_awaited_once_with("example.com")
    # PG UPDATE도 호출됨
    assert s.execute.await_count == 1
    s.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_domain_deactivation_qdrant_fail_returns_zero_but_pg_proceeds(monkeypatch):
    domain = FakeDomain(domain_id=1, host="example.com")
    s = MagicMock()
    s.execute = AsyncMock()
    s.commit = AsyncMock()

    fake_adapter = MagicMock()
    fake_adapter.delete_by_domain = AsyncMock(side_effect=RuntimeError("qdrant down"))
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)

    deleted = await mod.handle_domain_deactivation(s, domain=domain)
    assert deleted == 0
    s.commit.assert_awaited_once()  # PG는 그래도 처리
