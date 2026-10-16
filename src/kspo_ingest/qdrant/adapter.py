from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qdrant_client.http import models as qmodels
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kspo_ingest.db.models import Chunk as ChunkRow
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.bootstrap import CollectionStatus, ensure_collection
from kspo_ingest.qdrant.client import get_client
from kspo_ingest.settings import settings

log = get_logger("qdrant", "adapter")

# Qdrant 일시 장애 시 3회 재시도 (1s, 2s, 4s)
_QDRANT_RETRY = {
    "stop": stop_after_attempt(3),
    "wait": wait_exponential(multiplier=1, min=1, max=10),
    "retry": retry_if_exception_type((Exception,)),
    "reraise": True,
}


@dataclass
class QdrantPoint:
    qdrant_point_id: UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class UpsertResult:
    upserted: int
    elapsed_ms: int


@dataclass
class SyncResult:
    upserted: int
    deleted: int


class QdrantDirectAdapter:
    """Direct mode 어댑터 — Tiledesk-LLM `/api/ingestion`은 사용하지 않음 (CLAUDE.md 절대 금지)."""

    namespace = "kspo"

    def __init__(self) -> None:
        self.client = get_client()
        self.collection = settings.qdrant_index_name

    async def ensure_collection(self) -> CollectionStatus:
        return await ensure_collection()

    async def upsert_chunks(self, points: list[QdrantPoint]) -> UpsertResult:
        if not points:
            return UpsertResult(upserted=0, elapsed_ms=0)
        t0 = time.monotonic()
        async for attempt in AsyncRetrying(**_QDRANT_RETRY):
            with attempt:
                await self.client.upsert(
                    collection_name=self.collection,
                    points=[
                        qmodels.PointStruct(
                            id=str(p.qdrant_point_id),
                            vector=p.vector,
                            payload=p.payload,
                        )
                        for p in points
                    ],
                    wait=True,
                )
        elapsed = int((time.monotonic() - t0) * 1000)
        log.bind(
            event="qdrant_upsert_ok",
            collection=self.collection,
            count=len(points),
            elapsed_ms=elapsed,
        ).info("upsert ok")
        return UpsertResult(upserted=len(points), elapsed_ms=elapsed)

    async def upsert_to(self, collection: str, points: list[QdrantPoint]) -> UpsertResult:
        """지정된 컬렉션에 포인트 upsert (멀티 컬렉션 라우팅용)."""
        if not points:
            return UpsertResult(upserted=0, elapsed_ms=0)
        t0 = time.monotonic()
        async for attempt in AsyncRetrying(**_QDRANT_RETRY):
            with attempt:
                await self.client.upsert(
                    collection_name=collection,
                    points=[
                        qmodels.PointStruct(
                            id=str(p.qdrant_point_id),
                            vector=p.vector,
                            payload=p.payload,
                        )
                        for p in points
                    ],
                    wait=True,
                )
        elapsed = int((time.monotonic() - t0) * 1000)
        log.bind(
            event="qdrant_upsert_ok",
            collection=collection,
            count=len(points),
            elapsed_ms=elapsed,
        ).info("upsert ok")
        return UpsertResult(upserted=len(points), elapsed_ms=elapsed)

    async def delete_by_ids(self, point_ids: list[UUID]) -> None:
        if not point_ids:
            return
        await self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.PointIdsList(points=[str(pid) for pid in point_ids]),
            wait=True,
        )
        log.bind(
            event="qdrant_delete_ids",
            collection=self.collection,
            count=len(point_ids),
        ).info("delete by ids ok")

    async def delete_from_collection(
        self, collection: str, point_ids: list[UUID],
    ) -> None:
        """지정 컬렉션에서 포인트 삭제."""
        if not point_ids:
            return
        await self.client.delete(
            collection_name=collection,
            points_selector=qmodels.PointIdsList(
                points=[str(pid) for pid in point_ids],
            ),
            wait=True,
        )
        log.bind(
            event="qdrant_delete_from_collection",
            collection=collection,
            count=len(point_ids),
        ).info("delete from collection ok")

    async def move_points(
        self, from_col: str, to_col: str, point_ids: list[UUID]
    ) -> int:
        """from_col의 포인트를 벡터+페이로드째로 to_col에 재upsert 후 from_col에서 삭제.

        재임베딩 없이 컬렉션 이동(아카이브). retrieve로 벡터 회수 → upsert → delete.
        """
        if not point_ids:
            return 0
        ids = [str(pid) for pid in point_ids]
        records = await self.client.retrieve(
            collection_name=from_col,
            ids=ids,
            with_vectors=True,
            with_payload=True,
        )
        if not records:
            return 0
        await self.client.upsert(
            collection_name=to_col,
            points=[
                qmodels.PointStruct(id=r.id, vector=r.vector, payload=r.payload)
                for r in records
            ],
            wait=True,
        )
        await self.client.delete(
            collection_name=from_col,
            points_selector=qmodels.PointIdsList(points=ids),
            wait=True,
        )
        log.bind(
            event="qdrant_move_points",
            from_col=from_col,
            to_col=to_col,
            count=len(records),
        ).info("move ok")
        return len(records)

    async def delete_by_domain(self, domain_host: str) -> int:
        """metadata.domain_host == host인 모든 청크 삭제. 반환: 삭제 전 매칭 수."""
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="metadata.domain_host",
                    match=qmodels.MatchValue(value=domain_host),
                )
            ]
        )
        # 삭제 전 카운트 (metric용)
        try:
            count_result = await self.client.count(
                collection_name=self.collection,
                count_filter=flt,
                exact=True,
            )
            count = count_result.count
        except Exception:
            count = 0

        await self.client.delete(
            collection_name=self.collection,
            points_selector=qmodels.FilterSelector(filter=flt),
            wait=True,
        )
        log.bind(
            event="qdrant_delete_by_domain",
            collection=self.collection,
            domain=domain_host,
            count=count,
        ).info("delete by domain ok")
        return count

    async def replace_page_chunks(
        self,
        session: AsyncSession,
        *,
        page_id: int,
        embedding_version: int,
        new_points: list[QdrantPoint],
    ) -> SyncResult:
        """페이지 청크 동기화 (`§3.14`).

        기존 PG chunks(page_id, version)의 qdrant_point_id 집합과 새 집합을 diff:
          - 신규(또는 동일 id) → upsert (자연 갱신)
          - 사라진 id → Qdrant에서 delete

        주의: 본 메서드는 PG chunks를 직접 변경하지 않는다 — 호출자(Chunker.upsert_chunks_meta)가
        새 set으로 이미 갱신했어야 한다. Qdrant 측만 diff sync한다.
        """
        result = await session.execute(
            select(ChunkRow.qdrant_point_id).where(
                ChunkRow.page_id == page_id,
                ChunkRow.embedding_version == embedding_version,
                ChunkRow.is_attachment.is_(False),
            )
        )
        old_ids: set[UUID] = {row[0] for row in result.all()}
        new_ids: set[UUID] = {p.qdrant_point_id for p in new_points}

        await self.upsert_chunks(new_points)

        to_delete = list(old_ids - new_ids)
        if to_delete:
            await self.delete_by_ids(to_delete)

        return SyncResult(upserted=len(new_points), deleted=len(to_delete))
