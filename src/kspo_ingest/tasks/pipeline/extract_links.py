"""extract_links — 페이지 raw HTML에서 첨부·내부 링크를 발견하여 PG에 기록.

v2.0 Lite 정책:
- 첨부: 다운로드/추출/임베딩하지 않고 메타(URL/파일명/MIME)만 attachments에 upsert.
  챗봇은 `/files/{id}` 302 redirect로 source_url 직접 노출.
- 내부 링크(M4.T4.1 결선): 같은 host의 미발견 페이지 URL을 status=DISCOVERED로 pages에
  upsert. 다음 incremental Job(run_incremental)이 이를 frontier 대신 SELECT로 픽업하여
  실제 fetch→clean→refine→chunk 흐름에 흡수. 깊이 제한은 호출자가 page.depth+1로 부여,
  Domain.max_depth를 넘으면 skip.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from kspo_ingest.attach.discovery import (
    DiscoveredAttachment,
    discover_attachments,
    url_hash_sha256,
)
from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.crawl import storage as storage_paths
from kspo_ingest.crawl.board import classify_board_list
from kspo_ingest.crawl.board_detect import upsert_board_candidate
from kspo_ingest.crawl.domain_profile import detect_js_redirect, detect_meta_refresh
from kspo_ingest.crawl.dynamic import navigation_depth
from kspo_ingest.crawl.external_links import discover_external_links
from kspo_ingest.crawl.internal_links import discover_internal_links
from kspo_ingest.crawl.soma import discover_urls
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import Attachment, BoardSource, Domain, Page
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.tasks.jobs import is_cancelled

log = get_logger("worker", "extract_links")


async def extract_links(ctx: dict, *, job_id: int, page_id: int) -> dict[str, int]:
    """페이지의 첨부·내부 링크 추출. 반환: {"attachments": N, "discovered": M}.

    - attachments: UNIQUE(domain_id, file_hash) upsert 행 수
    - discovered: pages에 신규 status=DISCOVERED로 추가된 URL 수
    """
    session_factory = ctx["session_factory"]
    storage_root: Path = ctx["storage_root"]

    domain_id: int | None = None
    base_url: str | None = None
    html: str | None = None
    attach_count = 0
    discovered_count = 0

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return {"attachments": 0, "discovered": 0}

        page = await s.get(Page, page_id)
        if page is None:
            return {"attachments": 0, "discovered": 0}
        domain = await s.get(Domain, page.domain_id)
        if domain is None:
            return {"attachments": 0, "discovered": 0}

        raw_path = storage_paths.raw_path(storage_root, page.domain_id, page.url_hash)
        if not raw_path.is_file():
            log.bind(event="extract_links_no_raw", page_id=page_id).debug("raw missing")
            return {"attachments": 0, "discovered": 0}

        raw = raw_path.read_bytes()
        html = raw.decode(detect_encoding(raw, page.content_type), errors="replace")
        domain_id = page.domain_id
        base_url = (page.storage_paths or {}).get("final_url") or page.url

        attach_count = await _upsert_attachments(s, page=page, html=html)
        discovered_count = await _upsert_discovered_pages(
            s,
            page=page,
            domain=domain,
            html=html,
            redis=ctx.get("frontier").redis if ctx.get("frontier") else None,
            job_id=job_id,
        )

        log.bind(
            event="extract_links_ok",
            page_id=page_id,
            attachments=attach_count,
            discovered=discovered_count,
        ).info("links extracted")

    try:
        sig = classify_board_list(html, base_url=base_url)
        if sig.is_board and urlsplit(base_url).hostname == domain.host:
            from kspo_ingest.crawl.board_validation import entry_url

            entry = entry_url(base_url, domain.host)
            if (
                entry
                and "full_url_limit" in ctx
                and not await ctx["frontier"].admit_direct(
                    job_id, entry, limit=ctx["full_url_limit"]
                )
            ):
                return {"attachments": attach_count, "discovered": discovered_count}
            async with session_factory() as s2:
                await upsert_board_candidate(
                    s2,
                    domain_id=domain_id,
                    list_url=base_url,
                    html=html,
                    fetched_url=base_url,
                    fetcher=ctx.get("smart_fetcher"),
                )
    except Exception as exc:  # best-effort 탐지 — 실패해도 링크추출 결과에 영향 없음
        log.bind(event="board_detect_error", page_id=page_id, err=str(exc)).warning(
            "board detect skipped"
        )

    return {"attachments": attach_count, "discovered": discovered_count}


async def _upsert_attachments(s, *, page: Page, html: str) -> int:
    """첨부 메타 upsert (extraction_status=SKIPPED — Lite 정책)."""
    discovered: list[DiscoveredAttachment] = discover_attachments(
        html, base_url=(page.storage_paths or {}).get("final_url") or page.url
    )
    if not discovered:
        return 0

    rows = [
        {
            "page_id": page.id,
            "domain_id": page.domain_id,
            "source_url": d.source_url,
            "file_name": d.file_name,
            "mime_type": d.mime_type,
            "byte_size": None,
            "file_hash": url_hash_sha256(d.source_url),
            "storage_path": "",  # v2.0 Lite — 다운로드 안 함
            "text_path": None,
            "extracted_text": None,
            "extraction_status": "SKIPPED",
        }
        for d in discovered
    ]

    stmt = pg_insert(Attachment).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_attachments_domain_id_file_hash",
        set_={
            "page_id": stmt.excluded.page_id,
            "source_url": stmt.excluded.source_url,
            "file_name": stmt.excluded.file_name,
            "mime_type": stmt.excluded.mime_type,
            "extraction_status": "SKIPPED",
        },
    )
    await s.execute(stmt)
    await s.commit()
    return len(rows)


def crawlable_link_urls(html: str, *, base_url: str, host: str) -> list[str]:
    """같은 host의 크롤 대상 URL. `<a href>` 내부 링크에 더해, 페이지가 JS
    리다이렉트(`location.href=...`)나 meta refresh인 경우 그 목적지도 포함한다.

    KSPO 패밀리 다수(sportsvalue/sqms/nfa 등)는 홈이 JS 리다이렉트 shell이라
    `<a href>`가 없어, 목적지(`/main.kspo` 등)를 여기서 넣지 않으면 크롤이
    진입점에서 멈춘다. 목적지가 다른 host면(외부 리다이렉트) 제외한다.
    """
    if urlsplit(base_url).hostname != host:
        return []
    urls = list(discover_internal_links(html, base_url=base_url, host=host))
    urls.extend(u for u in discover_urls(html, base_url) if u not in urls)
    seen = set(urls)
    for target in (detect_js_redirect(html, base_url), detect_meta_refresh(html, base_url)):
        if target and urlsplit(target).hostname == host and target not in seen:
            urls.append(target)
            seen.add(target)
    urls.extend(
        link.url
        for link in discover_external_links(html, base_url=base_url, source_host=host)
        if link.url not in seen
    )
    return urls


async def _upsert_discovered_pages(
    s, *, page: Page, domain: Domain, html: str, redis=None, job_id: int | None = None
) -> int:
    """내부 링크 → 미발견 페이지를 status=DISCOVERED로 upsert.

    이미 존재하는 (domain_id, url_hash)는 ON CONFLICT DO NOTHING — 상태 보존.
    Domain.max_depth 초과 시 skip (현재 page.depth + 1 비교).
    """
    urls = crawlable_link_urls(
        html, base_url=(page.storage_paths or {}).get("final_url") or page.url, host=domain.host
    )
    from kspo_ingest.crawl.board_identity import is_board_owned_link

    confirmed = set((await s.execute(select(BoardSource.list_url).where(
        BoardSource.domain_id == domain.id, BoardSource.status == "confirmed"
    ))).scalars().all())
    urls = [u for u in urls if not is_board_owned_link(u, confirmed_list_urls=confirmed)]
    if not urls:
        return 0

    from kspo_ingest.crawl.loop_guard import list_family, list_signature

    family = list_family(page.url)
    if redis is not None and job_id is not None and family:
        signature = list_signature(page.url, urls)
        repeated = signature and not await redis.sadd(f"list_states:{job_id}", signature)
        if repeated:
            await redis.sadd(f"blocked_lists:{job_id}", family)
            await redis.incr(f"repeated_lists:{job_id}")
        if await redis.sismember(f"blocked_lists:{job_id}", family):
            # Keep details and links to other lists, stop this family's pagination.
            urls = [u for u in urls if list_family(u) != family]

    external = {
        link.url: link.label
        for link in discover_external_links(
            html,
            base_url=(page.storage_paths or {}).get("final_url") or page.url,
            source_host=domain.host,
        )
    }
    rows = []
    seen_hashes: set[str] = set()
    for raw_url in urls:
        next_depth = navigation_depth(page.url, raw_url, page.depth or 0)
        if next_depth > (domain.max_depth if domain.max_depth is not None else 10):
            continue
        normalized, url_hash = normalize_url(raw_url)
        if url_hash in seen_hashes:
            continue
        seen_hashes.add(url_hash)
        if redis is not None and job_id is not None:
            from kspo_ingest.crawl.frontier import Frontier

            if not await Frontier(redis).reserve_discovery(
                job_id, normalized, limit=min(domain.max_pages or 30000, 30000)
            ):
                continue
        rows.append(
            {
                "domain_id": page.domain_id,
                "url": normalized,
                "url_hash": url_hash,
                "depth": next_depth,
                "status": "DISCOVERED",
                "storage_paths": (
                    {"linked_from": page.url, "link_label": external[raw_url]}
                    if raw_url in external
                    else {}
                ),
            }
        )
    if not rows:
        return 0

    stmt = pg_insert(Page).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_pages_domain_id_url_hash")
    result = await s.execute(stmt)
    await s.commit()
    # rowcount: ON CONFLICT DO NOTHING 시 실제 INSERT된 행만 카운트
    return result.rowcount or 0
