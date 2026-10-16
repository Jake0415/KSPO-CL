"""GET /api/pages list + detail 단위 테스트.

session.execute / scalar 분기를 mock해 검증.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from kspo_ingest.api.routers import pages as pages_router


class FakePage:
    def __init__(self, page_id=1):
        self.id = page_id
        self.domain_id = 1
        self.url = f"https://example.com/{page_id}"
        self.url_hash = "a" * 40
        self.title = f"page {page_id}"
        self.status = "INDEXED"
        self.drop_reason = None
        self.http_status = 200
        self.last_http_status = 200
        self.content_type = "text/html"
        self.content_hash = "h" * 64
        self.depth = 1
        self.error_count = 0
        self.discovered_at = datetime.now(UTC)
        self.last_fetched_at = datetime.now(UTC)
        self.last_indexed_at = datetime.now(UTC)


class FakeChunk:
    def __init__(self, chunk_id, page_id):
        self.id = chunk_id
        self.chunk_index = chunk_id - 100
        self.is_attachment = False
        self.attachment_id = None
        self.token_len = 250
        self.embedding_model = "text-embedding-3-large"
        self.embed_status = "OK"
        self.kb_status = "OK"


def _make_session_list(pages):
    s = MagicMock()
    rows = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(pages))
    rows.scalars = MagicMock(return_value=scalars)
    s.execute = AsyncMock(return_value=rows)
    s.scalar = AsyncMock(return_value=0)
    return s


def _make_session_detail(page, chunks=()):
    s = MagicMock()
    s.get = AsyncMock(return_value=page)

    rows = MagicMock()
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=list(chunks))
    rows.scalars = MagicMock(return_value=scalars)
    s.execute = AsyncMock(return_value=rows)
    s.scalar = AsyncMock(return_value=len(chunks))
    return s


@pytest.mark.asyncio
async def test_list_pages_returns_rows():
    s = _make_session_list([FakePage(1), FakePage(2)])
    out = await pages_router.list_pages(
        domain_id=None, status_filter=None, q=None, limit=100, offset=0,
        s=s, _admin="admin",
    )
    assert len(out) == 2


@pytest.mark.asyncio
async def test_list_pages_filters_pass_through():
    """domain_id/status/q 인자 모두 .where()에 합쳐지는지 — 호출 자체 성공만 검증."""
    s = _make_session_list([])
    out = await pages_router.list_pages(
        domain_id=42, status_filter="INDEXED", q="test", limit=10, offset=0,
        s=s, _admin="admin",
    )
    assert out == []


@pytest.mark.asyncio
async def test_get_page_detail_returns_chunks_and_count():
    page = FakePage(10)
    chunks = [FakeChunk(101, 10), FakeChunk(102, 10)]
    s = _make_session_detail(page, chunks=chunks)
    s.scalar = AsyncMock(return_value=3)  # attachments_count

    out = await pages_router.get_page(id=10, s=s, _admin="admin")
    assert out.id == 10
    assert len(out.chunks) == 2
    assert out.attachments_count == 3


@pytest.mark.asyncio
async def test_get_page_404_when_missing():
    s = _make_session_detail(page=None)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await pages_router.get_page(id=999, s=s, _admin="admin")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_page_with_zero_chunks():
    page = FakePage(20)
    s = _make_session_detail(page, chunks=())
    out = await pages_router.get_page(id=20, s=s, _admin="admin")
    assert out.chunks == []
    assert out.attachments_count == 0
