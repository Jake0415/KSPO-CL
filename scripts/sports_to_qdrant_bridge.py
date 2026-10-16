"""sports.re.kr 전용 크롤러 SQLite → Qdrant 브리지.

이미 정제된 738개 문서를 메인 파이프라인의 chunk→embed→Qdrant 경로로 적재.
refine(LLM) 생략(텍스트가 이미 깔끔) — score는 휴리스틱, 임베딩만 수행.
"""
import asyncio, re, sqlite3
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import select
from kspo_ingest.settings import settings
from kspo_ingest.db.session import async_session
from kspo_ingest.db.models import Domain, CrawlJob
from kspo_ingest.tasks.jobs import empty_stats, finish_job, start_job
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page
from kspo_ingest.quality.scorer import ScorerInput, score_document
from kspo_ingest.quality.gate import upsert_doc_quality
from kspo_ingest.quality.embedding_policy import resolve_embedding_targets
from kspo_ingest.tasks.pipeline.chunk_and_index import chunk_and_index

HOST = "www.sports.re.kr"
DB = "/tmp/sports.db"

def parse_dt(s):
    if not s: return None
    s = str(s).strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return datetime.fromisoformat(s[:10]).replace(tzinfo=UTC)
        if re.match(r"^\d{4}$", s):
            return datetime(int(s), 1, 1, tzinfo=UTC)
    except Exception:
        return None
    return None

async def main():
    ctx = {"session_factory": async_session, "storage_root": Path(settings.storage_root)}
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    docs = c.execute("SELECT unit_type,title,body_text,posted_at,canonical_url,content_hash "
                     "FROM document WHERE body_text IS NOT NULL AND length(body_text)>0").fetchall()
    print(f"SQLite 문서 {len(docs)}개 로드")

    async with async_session() as s:
        d = (await s.execute(select(Domain).where(Domain.host == HOST))).scalar_one()
        domain_id = d.id
        job = CrawlJob(domain_id=domain_id, job_type="full", status="PENDING",
                       triggered_by="sports_bridge", stats=empty_stats())
        s.add(job); await s.commit(); await s.refresh(job); job_id = job.id
        await start_job(s, job_id)

    indexed = 0
    for i, doc in enumerate(docs):
        try:
            posted = parse_dt(doc["posted_at"])
            async with async_session() as s:
                page = await get_or_create_page(s, domain_id=domain_id, url=doc["canonical_url"],
                                                depth=1, posted_at=posted)
                page.title = doc["title"] or ""
                page.content_hash = doc["content_hash"]
                await s.commit()
                page_id = page.id
            score = score_document(ScorerInput(
                title=doc["title"], body_text=doc["body_text"],
                extraction_method="sports_crawler", posted_at=posted,
                summary=None, keywords=[], is_meaningful=True, domain_host=HOST))
            async with async_session() as s:
                await upsert_doc_quality(s, page_id=page_id, score=score)
            targets = resolve_embedding_targets(score)
            if not targets:
                continue
            n = await chunk_and_index(ctx, job_id=job_id, page_id=page_id,
                                      refined_text=doc["body_text"], summary=None, keywords=[],
                                      quality_score=score.quality_score, quadrant=score.quadrant,
                                      freshness_score=score.freshness_score,
                                      trust_score=score.trust_score, collections=targets)
            if n:
                indexed += 1
        except Exception as e:
            print(f"  doc {i} 실패: {type(e).__name__}: {str(e)[:80]}")
        if (i + 1) % 100 == 0:
            print(f"  진행 {i+1}/{len(docs)}, indexed={indexed}")

    async with async_session() as s:
        await finish_job(s, job_id, status="SUCCESS", error=None)
    print(f"완료: {indexed}/{len(docs)} 적재 (job {job_id})")

asyncio.run(main())
