"""push_to_sonar — refine 이후 SONAR KB로 1페이지 = 1문서 등록.

기존 `chunk_and_index`(로컬 청킹 + OpenAI 임베딩 + Qdrant upsert)를 대체한다.
SONAR가 자체 청킹·임베딩·sparse·upsert를 담당하므로 우리는 정제 텍스트만 넘긴다.

실패 정책:
  - 4xx: 즉시 실패, 재시도 무의미. errors++.
  - 5xx/네트워크: SonarClient가 지수 백오프 재시도. 소진 시 errors++.
  - 어느 경우든 page.status는 손대지 않는다 (재크롤/재시도 여지 유지).
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from kspo_ingest.clean.rag import VERSION, document_content
from kspo_ingest.crawl.url_normalize import canonical_url
from kspo_ingest.db.models import Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.sonar.client import SonarClient, SonarError
from kspo_ingest.sonar.kb_index import purge_kb_points
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled

log = get_logger("worker", "push_to_sonar")


async def push_to_sonar(
    ctx: dict,
    *,
    job_id: int,
    page_id: int,
    refined_text: str,
    summary: str | None,
    keywords: list[str],
) -> int:
    """페이지 1건을 SONAR KB에 등록. 반환: 1(성공) or 0(스킵/실패)."""
    session_factory = ctx["session_factory"]
    sonar: SonarClient | None = ctx.get("sonar_client")
    if sonar is None and ctx.get("local_direct_indexing"):
        from kspo_ingest.tasks.pipeline.chunk_and_index import chunk_and_index

        count = await chunk_and_index(
            ctx,
            job_id=job_id,
            page_id=page_id,
            refined_text=refined_text,
            summary=summary,
            keywords=keywords,
        )
        return int(count > 0)
    if sonar is None:
        # 개발/PoC: SONAR 미설정 시 no-op. 파이프라인이 끊기지 않도록 skip 처리.
        log.bind(event="sonar_disabled", page_id=page_id).info("SONAR 미설정 — skip")
        return 0

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return 0
        page = await s.get(Page, page_id)
        if page is None:
            log.bind(event="sonar_no_page", page_id=page_id).warning("page missing")
            return 0
        domain = await s.get(Domain, page.domain_id)
        if domain is None:
            log.bind(event="sonar_no_domain", page_id=page_id).warning("domain missing")
            return 0
        # SONAR source는 정체성 canonical URL로 보낸다 — 같은 글이 크롤 시점의
        # pageIndex/searchWrd 차이로 다른 URL이 돼도 하나로 수렴해 SONAR upsert가
        # 중복을 방지한다(재크롤 멱등). fetch는 원본 URL로 이미 끝난 상태.
        page_url = canonical_url(page.url)
        page_title = page.title or page_url
        domain_host = urlsplit(page.url).hostname or domain.host

    # SONAR content = title + summary + refined_text. SONAR가 다시 청킹하므로 통합 전달.
    content = document_content(
        title=page_title, source_url=page_url, body=refined_text, summary=summary
    )

    tags = ["kspo", "ingest", f"d:{domain_host}", VERSION]
    if keywords:
        tags.extend(f"k:{k}" for k in keywords[:10])

    try:
        result = await sonar.upsert_kb(
            name=page_title,
            content=content,
            source=page_url,
            namespace=ctx["sonar_namespace"],
            tags=tags,
        )
    except SonarError as exc:
        log.bind(
            event="sonar_push_error",
            page_id=page_id,
            url=page_url,
            err=str(exc)[:300],
        ).warning("sonar push failed")
        async with session_factory() as s:
            await bump_stats(s, job_id, errors=1)
        return 0

    kb_id = (result.get("value") or {}).get("_id")

    # upsert만으로는 mongo에 status:-1로 방치됨. tiledesk-server의 scrape/single
    # 트리거를 명시 호출해야 워커 큐에 실려 임베딩·Qdrant 색인이 실제 진행된다.
    # Registration/trigger failures remain retryable; never count them as INDEXED.
    if not kb_id:
        async with session_factory() as s:
            await bump_stats(s, job_id, errors=1)
        return 0
    if kb_id:
        try:
            # 재색인 멱등성: 재스크랩 전 이 kb_id의 기존 Qdrant point를 제거해
            # 같은 문서가 매 색인마다 복제되는 것을 막는다.
            await purge_kb_points(kb_id)
            await sonar.trigger_scrape_single(
                kb_id=kb_id, namespace=ctx["sonar_namespace"], kb_type="text"
            )
        except SonarError as exc:
            log.bind(
                event="sonar_scrape_trigger_error",
                page_id=page_id,
                kb_id=kb_id,
                err=str(exc)[:300],
            ).warning("scrape/single trigger failed — 문서는 mongo에 저장됐으나 색인 미완")
            async with session_factory() as s:
                await bump_stats(s, job_id, errors=1)
            return 0

    async with session_factory() as s:
        page = await s.get(Page, page_id)
        if page is not None:
            page.status = "INDEXED"
            page.last_indexed_at = datetime.now(UTC)
        await bump_stats(s, job_id, indexed=1)
        await s.commit()

    log.bind(
        event="sonar_push_ok",
        page_id=page_id,
        url=page_url,
        kb_id=kb_id,
        content_len=len(content),
    ).info("pushed to sonar")
    return 1
