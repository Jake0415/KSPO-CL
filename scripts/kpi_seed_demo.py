#!/usr/bin/env python
"""KPI 측정 검증용 데모 데이터 seed.

PG에 다음을 insert:
- 도메인 1개 (demo.kspo.example)
- 페이지 10건 — INDEXED 8 / DROPPED 1 / ERROR 1
- 청크 16건 (INDEXED 페이지당 평균 2개)
- llm_usage 8행 — 이번 달 (refine) + 이번 달 (embedding)
- crawl_jobs 10건 — SUCCESS 9 / FAILED 1 (최근 7일 내)

본 시드는 idempotent하지 않음 — 실행 전 PG가 깨끗한 상태이거나 기존 데이터와 충돌
없는 host값으로 변경 권장.

사용법:
    python scripts/kpi_seed_demo.py
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from kspo_ingest.db.models import Chunk, CrawlJob, Domain, LlmUsage, Page
from kspo_ingest.db.session import async_session

_HOST = "demo.kspo.example"


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


async def seed() -> None:
    async with async_session() as s:
        # Domain
        d = Domain(
            host=_HOST,
            scheme="https",
            display_name="KPI demo",
            max_depth=10,
            max_pages=100,
            rate_limit_rps=Decimal("1.0"),
            concurrency=2,
            is_active=True,
            incremental_enabled=False,
        )
        s.add(d)
        await s.commit()
        await s.refresh(d)

        now = datetime.now(UTC)
        pages: list[Page] = []
        # 8 INDEXED
        for i in range(8):
            url = f"https://{_HOST}/article/{i}"
            p = Page(
                domain_id=d.id,
                url=url,
                url_hash=_url_hash(url),
                http_status=200,
                last_http_status=200,
                content_type="text/html",
                content_hash=hashlib.sha256(f"body{i}".encode()).hexdigest(),
                title=f"article {i}",
                depth=1,
                discovered_at=now - timedelta(days=2),
                last_fetched_at=now - timedelta(hours=12),
                last_indexed_at=now - timedelta(hours=12),
                status="INDEXED",
            )
            s.add(p)
            pages.append(p)
        # 1 DROPPED
        url = f"https://{_HOST}/article/8"
        s.add(
            Page(
                domain_id=d.id, url=url, url_hash=_url_hash(url),
                status="DROPPED", drop_reason="not_meaningful",
                discovered_at=now - timedelta(days=2),
                last_fetched_at=now - timedelta(hours=18),
            )
        )
        # 1 ERROR
        url = f"https://{_HOST}/article/9"
        s.add(
            Page(
                domain_id=d.id, url=url, url_hash=_url_hash(url),
                status="ERROR", error_count=2,
                discovered_at=now - timedelta(days=2),
                last_fetched_at=now - timedelta(hours=6),
            )
        )
        await s.commit()
        for p in pages:
            await s.refresh(p)

        # Chunks (INDEXED 페이지당 2개)
        for p in pages:
            for idx in range(2):
                sha1 = hashlib.sha1(f"{p.id}-{idx}".encode()).hexdigest()
                s.add(
                    Chunk(
                        chunk_id_sha1=sha1,
                        qdrant_point_id=uuid4(),
                        page_id=p.id,
                        is_attachment=False,
                        chunk_index=idx,
                        token_len=random.randint(120, 480),
                        embedding_model="text-embedding-3-large",
                        embedding_version=1,
                        embed_status="OK",
                        kb_status="OK",
                    )
                )
        await s.commit()

        # llm_usage — refine 5 + embedding 3 (이번 달)
        for i, purpose in enumerate(["refine"] * 5 + ["embedding"] * 3):
            s.add(
                LlmUsage(
                    page_id=pages[i % len(pages)].id,
                    purpose=purpose,
                    model="gpt-5.4-mini" if purpose == "refine" else "text-embedding-3-large",
                    prompt_tokens=1500,
                    completion_tokens=400 if purpose == "refine" else 0,
                    total_tokens=1900 if purpose == "refine" else 1500,
                    cost_usd=Decimal("0.001500"),
                    created_at=now - timedelta(hours=i + 1),
                )
            )

        # crawl_jobs — SUCCESS 9 + FAILED 1 (최근 7일)
        for i in range(9):
            s.add(
                CrawlJob(
                    domain_id=d.id, job_type="full",
                    status="SUCCESS",
                    triggered_by="admin",
                    started_at=now - timedelta(days=i // 2),
                    finished_at=now - timedelta(days=i // 2, hours=-1),
                    stats={
                        "fetched": 1, "refined": 1, "indexed": 1,
                        "errors": 0, "dropped": 0, "skipped": 0, "removed": 0, "discovered": 1,
                    },
                    created_at=now - timedelta(days=i // 2),
                )
            )
        s.add(
            CrawlJob(
                domain_id=d.id, job_type="full",
                status="FAILED",
                triggered_by="admin",
                error_message="openai_429",
                stats={
                    "fetched": 0, "refined": 0, "indexed": 0,
                    "errors": 1, "dropped": 0, "skipped": 0, "removed": 0, "discovered": 0,
                },
                created_at=now - timedelta(days=1),
            )
        )
        await s.commit()
        print(f"seeded: domain_id={d.id}, pages={len(pages) + 2}, chunks={len(pages) * 2}")


if __name__ == "__main__":
    asyncio.run(seed())
