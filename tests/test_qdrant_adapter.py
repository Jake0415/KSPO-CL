"""QdrantDirectAdapter 통합 테스트 — 자체 Qdrant 컨테이너 필요.

기본 실행 제외(`-m 'not qdrant_integration'`). 명시 실행:
    KSPO_TEST_QDRANT_URL=http://localhost:6333 pytest -m qdrant_integration

QDRANT_URL 미설정 환경에서는 모듈 전체 skip.
"""
from __future__ import annotations

import contextlib
import os
import socket
import uuid
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import pytest

pytestmark = pytest.mark.qdrant_integration


def _qdrant_reachable(url: str) -> bool:
    try:
        u = urlparse(url)
        with socket.create_connection((u.hostname or "localhost", u.port or 6333), timeout=2):
            return True
    except OSError:
        return False


_TEST_QDRANT_URL = os.getenv("KSPO_TEST_QDRANT_URL", "")
if not _TEST_QDRANT_URL or not _qdrant_reachable(_TEST_QDRANT_URL):
    pytest.skip(
        "KSPO_TEST_QDRANT_URL 미설정 또는 Qdrant 미가용 — 통합 테스트 skip",
        allow_module_level=True,
    )


@pytest.fixture
async def adapter() -> AsyncIterator:
    """테스트마다 별도 컬렉션을 만들고 종료 시 삭제."""
    from kspo_ingest.qdrant import client as qclient
    from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
    from kspo_ingest.settings import settings

    saved_url = settings.qdrant_url
    saved_name = settings.qdrant_index_name
    settings.qdrant_url = _TEST_QDRANT_URL
    settings.qdrant_index_name = f"kspo_test_{uuid.uuid4().hex[:8]}"
    qclient.reset_client_for_tests()

    a = QdrantDirectAdapter()
    status = await a.ensure_collection()
    assert status.healthy, f"ensure_collection failed: {status.error}"

    try:
        yield a
    finally:
        with contextlib.suppress(Exception):
            await a.client.delete_collection(collection_name=a.collection)
        settings.qdrant_url = saved_url
        settings.qdrant_index_name = saved_name
        qclient.reset_client_for_tests()


def _make_point(point_id: uuid.UUID, *, domain: str, page_id: int, vector_seed: float = 0.1):
    from kspo_ingest.qdrant.adapter import QdrantPoint

    return QdrantPoint(
        qdrant_point_id=point_id,
        vector=[vector_seed] * 3072,
        payload={
            "page_content": f"text for {page_id}",
            "metadata": {
                "id": point_id.hex,
                "source": f"https://{domain}/p/{page_id}",
                "domain_host": domain,
                "namespace": "kspo",
                "type": "text",
                "is_attachment": False,
                "embedding_version": 1,
                "tags": [f"d:{domain}", "is_att:0", "v:1"],
            },
        },
    )


async def test_ensure_collection_creates_when_missing(adapter):
    """fixture에서 이미 ensure_collection 호출 — 멱등성 검증."""
    status = await adapter.ensure_collection()
    assert status.exists is True
    assert status.dim == 3072
    assert status.healthy is True


async def test_upsert_chunks_returns_count_and_elapsed(adapter):
    points = [_make_point(uuid.uuid4(), domain="a.com", page_id=i) for i in range(3)]
    r = await adapter.upsert_chunks(points)
    assert r.upserted == 3
    assert r.elapsed_ms >= 0


async def test_upsert_then_count(adapter):
    from qdrant_client.http import models as qmodels

    pts = [_make_point(uuid.uuid4(), domain="a.com", page_id=i) for i in range(5)]
    await adapter.upsert_chunks(pts)
    count = (
        await adapter.client.count(collection_name=adapter.collection, exact=True)
    ).count
    assert count == 5
    _ = qmodels  # suppress unused


async def test_delete_by_ids(adapter):
    pts = [_make_point(uuid.uuid4(), domain="a.com", page_id=i) for i in range(3)]
    await adapter.upsert_chunks(pts)
    await adapter.delete_by_ids([pts[0].qdrant_point_id])
    count = (
        await adapter.client.count(collection_name=adapter.collection, exact=True)
    ).count
    assert count == 2


async def test_delete_by_domain_filters_by_host(adapter):
    a_pts = [_make_point(uuid.uuid4(), domain="a.com", page_id=i) for i in range(5)]
    b_pts = [_make_point(uuid.uuid4(), domain="b.com", page_id=i) for i in range(3)]
    await adapter.upsert_chunks(a_pts + b_pts)

    deleted = await adapter.delete_by_domain("a.com")
    assert deleted == 5

    remaining = (
        await adapter.client.count(collection_name=adapter.collection, exact=True)
    ).count
    assert remaining == 3


async def test_replace_page_chunks_no_pg_diff(adapter):
    """PG 비교 없이 — old set이 비어있는 케이스 (신규 페이지 인덱싱)."""
    from unittest.mock import AsyncMock

    pts = [_make_point(uuid.uuid4(), domain="a.com", page_id=1) for _ in range(3)]
    session = AsyncMock()
    result_mock = AsyncMock()
    result_mock.all.return_value = []
    session.execute.return_value = result_mock

    sync = await adapter.replace_page_chunks(
        session, page_id=1, embedding_version=1, new_points=pts
    )
    assert sync.upserted == 3
    assert sync.deleted == 0


async def test_replace_page_chunks_deletes_orphans(adapter):
    """old set이 new set보다 많으면 차이만큼 delete."""
    from unittest.mock import AsyncMock

    keep_ids = [uuid.uuid4() for _ in range(2)]
    drop_ids = [uuid.uuid4() for _ in range(2)]
    all_old = [
        _make_point(pid, domain="a.com", page_id=1) for pid in keep_ids + drop_ids
    ]
    await adapter.upsert_chunks(all_old)

    new_pts = [_make_point(pid, domain="a.com", page_id=1) for pid in keep_ids]
    session = AsyncMock()
    result_mock = AsyncMock()
    result_mock.all.return_value = [(pid,) for pid in keep_ids + drop_ids]
    session.execute.return_value = result_mock

    sync = await adapter.replace_page_chunks(
        session, page_id=1, embedding_version=1, new_points=new_pts
    )
    assert sync.upserted == 2
    assert sync.deleted == 2

    remaining = (
        await adapter.client.count(collection_name=adapter.collection, exact=True)
    ).count
    assert remaining == 2


async def test_empty_upsert_is_noop(adapter):
    r = await adapter.upsert_chunks([])
    assert r.upserted == 0
    assert r.elapsed_ms == 0
