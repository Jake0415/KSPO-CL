from __future__ import annotations

from uuid import uuid4

import pytest

from kspo_ingest.qdrant.adapter import QdrantDirectAdapter


class _FakeRecord:
    def __init__(self, pid, vector, payload):
        self.id = str(pid)
        self.vector = vector
        self.payload = payload


class _FakeClient:
    def __init__(self):
        self.upserted = {}
        self.deleted = {}
        self._store = {}

    async def retrieve(self, collection_name, ids, with_vectors, with_payload):
        return [self._store[i] for i in ids if i in self._store]

    async def upsert(self, collection_name, points, wait):
        self.upserted[collection_name] = points

    async def delete(self, collection_name, points_selector, wait):
        self.deleted[collection_name] = points_selector


@pytest.mark.asyncio
async def test_move_points_moves_vectors_without_reembed():
    pid = uuid4()
    adapter = QdrantDirectAdapter()
    fake = _FakeClient()
    fake._store[str(pid)] = _FakeRecord(pid, [0.1] * 3072, {"page_content": "x"})
    adapter.client = fake

    moved = await adapter.move_points("tilellm", "kspo_archive", [pid])
    assert moved == 1
    assert "kspo_archive" in fake.upserted
    assert "tilellm" in fake.deleted


@pytest.mark.asyncio
async def test_move_points_empty_noop():
    adapter = QdrantDirectAdapter()
    adapter.client = _FakeClient()
    assert await adapter.move_points("a", "b", []) == 0
