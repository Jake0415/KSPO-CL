"""코퍼스 scheme 쌍둥이/구버전 해시 중복 정리 + 랜딩 허브 적재 정리.

    # 중복 현황만 리포트 (아무것도 안 지움) — 기본 동작
    uv run python scripts/dedup_scheme_twins.py
    # 실제 정리
    uv run python scripts/dedup_scheme_twins.py --execute
    # 이미 적재된 랜딩 허브도 함께 DROPPED 정리
    uv run python scripts/dedup_scheme_twins.py --execute --purge-hubs
"""
from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, update

from kspo_ingest.crawl.url_class import is_landing_hub
from kspo_ingest.db.models import Chunk, LlmUsage, Page
from kspo_ingest.db.session import async_session
from kspo_ingest.maintenance.dedup import PageRow, find_duplicate_groups
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
from kspo_ingest.settings import settings


async def _delete_qdrant_points(
    adapter: QdrantDirectAdapter,
    page_ids: list[int],
    session,
) -> int:
    """page_ids 의 chunks.qdrant_point_id 를 두 컬렉션에서 삭제."""
    rows = await session.execute(
        select(Chunk.qdrant_point_id).where(Chunk.page_id.in_(page_ids))
    )
    point_ids = [r[0] for r in rows.all() if r[0] is not None]
    if not point_ids:
        return 0
    for col in (settings.qdrant_index_name, settings.qdrant_knowledge_collection):
        try:
            await adapter.delete_from_collection(col, point_ids)
        except Exception as exc:  # noqa: BLE001 — KB 정합성 우선, 로그만
            print(f"  [warn] qdrant delete skipped ({col}): {exc}")
    return len(point_ids)


async def run(execute: bool, purge_hubs: bool) -> None:
    adapter = QdrantDirectAdapter()

    async with async_session() as s:
        result = await s.execute(select(Page.id, Page.url, Page.depth, Page.status))
        page_rows = [
            PageRow(
                id=row.id,
                url=row.url,
                scheme=urlparse(row.url).scheme or "https",
                depth=row.depth,
                status=row.status,
            )
            for row in result.all()
        ]

    dups = find_duplicate_groups(page_rows)
    loser_ids = [r.id for _canon, losers in dups for r in losers]

    print(f"중복 그룹: {len(dups)}개 / 제거 예정 page: {len(loser_ids)}건")

    hub_ids: list[int] = []
    if purge_hubs:
        loser_set = set(loser_ids)
        hub_ids = [
            r.id
            for r in page_rows
            if r.status == "INDEXED" and is_landing_hub(r.url) and r.id not in loser_set
        ]
        print(f"적재된 랜딩 허브(DROPPED 예정): {len(hub_ids)}건")

    if not execute:
        # dry-run: Qdrant 포인트 예상 건수만 계산
        all_ids = loser_ids + hub_ids
        if all_ids:
            async with async_session() as s:
                cnt = await s.scalar(
                    select(func.count()).select_from(Chunk).where(Chunk.page_id.in_(all_ids))
                )
        else:
            cnt = 0
        print(f"[dry-run] 삭제 예정 Qdrant 포인트(≈chunks): {cnt}")
        print("[dry-run] --execute 없이는 아무것도 변경하지 않음.")
        return

    # ---- execute ----
    async with async_session() as s:
        # 1) 중복 loser: Qdrant 포인트 삭제 → llm_usage 재지정 → page 삭제(CASCADE)
        for canon, losers in dups:
            ids = [r.id for r in losers]
            if not ids:
                continue
            await _delete_qdrant_points(adapter, ids, s)
            await s.execute(
                update(LlmUsage).where(LlmUsage.page_id.in_(ids)).values(page_id=canon.id)
            )
            await s.execute(delete(Page).where(Page.id.in_(ids)))
            await s.commit()

        # 2) 랜딩 허브: Qdrant 포인트 삭제 → PG chunks 삭제 → status=DROPPED
        #    (page row는 유지 — 허브는 crawl/link 발견 진입점이므로 남긴다)
        if hub_ids:
            await _delete_qdrant_points(adapter, hub_ids, s)
            await s.execute(delete(Chunk).where(Chunk.page_id.in_(hub_ids)))
            await s.execute(
                update(Page).where(Page.id.in_(hub_ids)).values(status="DROPPED")
            )
            await s.commit()

    print("완료.")


def main() -> None:
    ap = argparse.ArgumentParser(description="코퍼스 중복 정리 + 랜딩 허브 정리")
    ap.add_argument("--execute", action="store_true", help="실제 삭제 수행(미지정 시 dry-run)")
    ap.add_argument(
        "--purge-hubs",
        action="store_true",
        help="이미 적재된 랜딩 허브도 DROPPED 정리 (--execute 와 함께일 때만 실제 반영; 단독 시 dry-run)",
    )
    args = ap.parse_args()
    asyncio.run(run(execute=args.execute, purge_hubs=args.purge_hubs))


if __name__ == "__main__":
    main()
