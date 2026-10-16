"""chunk_and_index 결선 task 단위 테스트.

embed/qdrant 호출은 mocking. PG/storage는 실제 호출 없이 session_factory mock.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from kspo_ingest.tasks.pipeline import chunk_and_index as mod


class FakePage:
    def __init__(self):
        self.url = "https://www.kspo.or.kr/"
        self.title = "테스트"
        self.posted_at = None
        self.domain_id = 1
        self.status = "REFINED"
        self.last_indexed_at = None


class FakeDomain:
    def __init__(self):
        self.host = "www.kspo.or.kr"


def _make_session_factory(*, page=None, domain=None, chunk_rows=None):
    """async session_factory fixture — context manager + .get / .commit 등 stub."""
    session = MagicMock()
    session.get = AsyncMock(side_effect=lambda model, _id: {
        type(page) if page else type(None): page,
        type(domain) if domain else type(None): domain,
    }.get(model))

    async def _get(model, _id):
        from kspo_ingest.db.models import Domain, Page
        if model is Page:
            return page
        if model is Domain:
            return domain
        return None

    session.get = AsyncMock(side_effect=_get)
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    if chunk_rows is not None:
        result = MagicMock()
        result.scalars = MagicMock(return_value=iter(chunk_rows))
        session.execute = AsyncMock(return_value=result)

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


@pytest.mark.asyncio
async def test_chunk_and_index_short_page_creates_one_chunk(monkeypatch, tmp_path):
    page = FakePage()
    domain = FakeDomain()
    factory, _session = _make_session_factory(page=page, domain=domain, chunk_rows=[])

    fake_chunk = MagicMock()
    fake_chunk.chunk_id_sha1 = "abc123"
    fake_chunk.qdrant_point_id = UUID("00000000-0000-0000-0000-000000000001")
    fake_chunk.text = "[제목] 테스트\n[도메인] www.kspo.or.kr\n\n— 본문 —\n본문"
    fake_chunk.token_len = 30
    fake_chunk.is_attachment = False
    fake_chunk.attachment_id = None

    monkeypatch.setattr(mod, "chunk_page", lambda inp: [fake_chunk])
    monkeypatch.setattr(mod, "write_chunks_jsonl", lambda *a, **k: tmp_path / "chunks.jsonl")
    monkeypatch.setattr(mod, "upsert_chunks_meta", AsyncMock(return_value=[101]))
    monkeypatch.setattr(
        mod,
        "is_cancelled",
        AsyncMock(return_value=False),
    )

    embed_result = MagicMock()
    embed_result.embedded = [MagicMock(chunk_id=101, vector=[0.1] * 8)]
    embed_result.success_chunk_ids = [101]
    embed_result.error_chunk_ids = []
    monkeypatch.setattr(mod, "embed_chunks", AsyncMock(return_value=embed_result))

    sync_result = MagicMock(upserted=1, deleted=0)
    fake_adapter = MagicMock()
    fake_adapter.replace_page_chunks = AsyncMock(return_value=sync_result)
    monkeypatch.setattr(mod, "QdrantDirectAdapter", lambda: fake_adapter)
    monkeypatch.setattr(mod, "bump_stats", AsyncMock())
    monkeypatch.setattr(mod, "_mark_indexed", AsyncMock())

    ctx = {"session_factory": factory, "storage_root": Path(tmp_path)}
    upserted = await mod.chunk_and_index(
        ctx,
        job_id=1,
        page_id=1,
        refined_text="본문",
        summary="요약",
        keywords=["k1", "k2"],
    )

    assert upserted == 1
    fake_adapter.replace_page_chunks.assert_awaited_once()
    mod._mark_indexed.assert_awaited_once()
    mod.bump_stats.assert_awaited_once()


@pytest.mark.asyncio
async def test_chunk_and_index_no_chunks_returns_zero(monkeypatch, tmp_path):
    page = FakePage()
    domain = FakeDomain()
    factory, _ = _make_session_factory(page=page, domain=domain)

    monkeypatch.setattr(mod, "chunk_page", lambda inp: [])
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))
    monkeypatch.setattr(mod, "upsert_chunks_meta", AsyncMock(return_value=[]))

    ctx = {"session_factory": factory, "storage_root": Path(tmp_path)}
    r = await mod.chunk_and_index(
        ctx, job_id=1, page_id=1, refined_text="", summary=None, keywords=[]
    )
    assert r == 0


@pytest.mark.asyncio
async def test_chunk_and_index_all_embed_fail_returns_zero(monkeypatch, tmp_path):
    page = FakePage()
    domain = FakeDomain()
    factory, _ = _make_session_factory(page=page, domain=domain)

    fake_chunk = MagicMock()
    fake_chunk.chunk_id_sha1 = "abc"
    fake_chunk.qdrant_point_id = UUID("00000000-0000-0000-0000-000000000001")
    fake_chunk.text = "x"
    monkeypatch.setattr(mod, "chunk_page", lambda inp: [fake_chunk])
    monkeypatch.setattr(mod, "write_chunks_jsonl", lambda *a, **k: tmp_path / "chunks.jsonl")
    monkeypatch.setattr(mod, "upsert_chunks_meta", AsyncMock(return_value=[101]))
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))

    embed_result = MagicMock()
    embed_result.embedded = []
    embed_result.success_chunk_ids = []
    embed_result.error_chunk_ids = [101]
    monkeypatch.setattr(mod, "embed_chunks", AsyncMock(return_value=embed_result))

    ctx = {"session_factory": factory, "storage_root": Path(tmp_path)}
    r = await mod.chunk_and_index(
        ctx, job_id=1, page_id=1, refined_text="본문", summary=None, keywords=[]
    )
    assert r == 0


@pytest.mark.asyncio
async def test_chunk_and_index_cancelled_short_circuits(monkeypatch, tmp_path):
    factory, _ = _make_session_factory()
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        mod, "chunk_page", MagicMock(side_effect=AssertionError("must not be called"))
    )

    ctx = {"session_factory": factory, "storage_root": Path(tmp_path)}
    r = await mod.chunk_and_index(
        ctx, job_id=1, page_id=1, refined_text="x", summary=None, keywords=[]
    )
    assert r == 0


@pytest.mark.asyncio
async def test_chunk_and_index_no_page_returns_zero(monkeypatch, tmp_path):
    factory, _ = _make_session_factory(page=None)
    monkeypatch.setattr(mod, "is_cancelled", AsyncMock(return_value=False))

    ctx = {"session_factory": factory, "storage_root": Path(tmp_path)}
    r = await mod.chunk_and_index(
        ctx, job_id=1, page_id=999, refined_text="x", summary=None, keywords=[]
    )
    assert r == 0
