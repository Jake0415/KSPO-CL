"""clean_page ARQ task — raw 디코딩 → 본문 추출 → content_hash 갱신.

incremental Job(M4.T4.1) 결선: content_hash 미변경 페이지는 LLM·임베딩 비용 0으로
SKIPPED 처리하여 last_fetched_at만 갱신 후 즉시 반환. caller(enqueue_seeds /
run_incremental)는 반환값의 `skipped=True`를 보고 후속 refine/chunk 생략.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from kspo_ingest.attach.discovery import discover_attachments
from kspo_ingest.clean.date_extract import extract_posted_at
from kspo_ingest.clean.extractor import ExtractionResult, extract
from kspo_ingest.clean.hash import normalize_for_hash
from kspo_ingest.clean.rag import VERSION, normalize_text
from kspo_ingest.clean.selectors import load_global_selectors
from kspo_ingest.crawl import storage as storage_paths
from kspo_ingest.crawl.external_links import (
    discover_external_links,
    external_access_blocked,
    external_metadata,
)
from kspo_ingest.crawl.soma import HOST as SOMA_HOST
from kspo_ingest.crawl.soma import detail_content
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.refine.pre_rules import ENGLISH_EXCLUSION_THRESHOLD, english_ratio
from kspo_ingest.tasks.jobs import bump_stats, is_cancelled
from kspo_ingest.tasks.pipeline.helpers import mark_dropped, mark_error

log = get_logger("worker", "clean_page")


_GLOBAL_SELECTORS: list[str] | None = None


def _get_global_selectors() -> list[str]:
    global _GLOBAL_SELECTORS
    if _GLOBAL_SELECTORS is None:
        _GLOBAL_SELECTORS = load_global_selectors()
    return _GLOBAL_SELECTORS


async def clean_page(ctx: dict, *, job_id: int, page_id: int, force: bool = False) -> dict | None:
    """raw HTML을 디코딩 + 본문 추출 후 content_hash 반환.

    incremental(M4.T4.1)에서 content_hash 미변경 페이지는 SKIPPED. refresh-url(M4.T4.2)
    `force=True`는 hash 비교를 건너뛰어 무조건 refine 진입.
    """
    session_factory = ctx["session_factory"]
    storage_root: Path = ctx["storage_root"]

    async with session_factory() as s:
        if await is_cancelled(s, job_id):
            return None

        from kspo_ingest.db.models import Domain, Page

        page = await s.get(Page, page_id)
        if page is None:
            return None
        domain = await s.get(Domain, page.domain_id)

        raw_path = storage_paths.raw_path(storage_root, page.domain_id, page.url_hash)
        if not raw_path.is_file():
            await mark_error(s, page_id, error="raw_missing")
            await bump_stats(s, job_id, errors=1)
            return None

        raw_bytes = raw_path.read_bytes()
        result = extract(
            raw_bytes,
            content_type=page.content_type,
            blacklist=[*_get_global_selectors(), *(domain.selector_blacklist or [])],
        )
        if urlsplit(page.url).hostname == SOMA_HOST:
            popup = detail_content(result.raw_html_decoded)
            if popup:
                result = ExtractionResult(
                    popup[0], popup[1], "main_article", result.raw_html_decoded
                )
        from selectolax.parser import HTMLParser

        revealed = HTMLParser(result.raw_html_decoded).css("[data-rag-dynamic]")
        if revealed:
            result.body_text += "\n동적 탐색으로 확인한 정보\n" + "\n".join(
                node.text(separator="\n", strip=True) for node in revealed
            )
        # Classify actual extracted source text before adding Korean labels/LLM content.
        if english_ratio(result.body_text) >= ENGLISH_EXCLUSION_THRESHOLD:
            await mark_dropped(s, page_id, reason="english_majority")
            await bump_stats(s, job_id, dropped=1, drop_reasons__english_majority=1)
            return None
        if urlsplit(page.url).hostname != domain.host:
            if external_access_blocked(result.raw_html_decoded):
                await mark_error(s, page_id, error="external_access_blocked")
                await bump_stats(s, job_id, errors=1)
                return None
            meta_title, description = external_metadata(result.raw_html_decoded)
            if meta_title:
                result.title = meta_title
            if description:
                result.body_text += "\n공개 페이지 정보\n" + description
            relation = page.storage_paths or {}
            if relation.get("linked_from"):
                result.body_text += "\n연결한 원문 페이지: " + relation["linked_from"]
        else:
            external_refs = discover_external_links(
                result.raw_html_decoded, base_url=page.url, source_host=domain.host
            )
            if external_refs:
                result.body_text += "\n외부 링크 정보 (본문 확보 여부와 별개)\n" + "\n".join(
                    link.label + "\n" + link.url for link in external_refs
                )
        attachments = discover_attachments(result.raw_html_decoded, base_url=page.url)
        if attachments:
            result.body_text += "\n첨부파일 정보 (본문 추출 없음)\n" + "\n".join(
                item.file_name + "\n" + item.source_url for item in attachments
            )
        result.body_text = normalize_text(result.body_text)
        new_hash = normalize_for_hash(
            VERSION + "\n" + (result.title or "") + "\n" + result.body_text
        )

        # Incremental skip — content_hash 미변경 시 LLM·임베딩 비용 0으로 즉시 종료.
        # last_fetched_at만 갱신하고 status는 보존(INDEXED/REFINED 등 그대로).
        # refresh-url(M4.T4.2) force=True면 비교를 건너뛰어 무조건 refine 진입.
        if not force and page.content_hash and page.content_hash == new_hash:
            page.last_fetched_at = datetime.now(UTC)
            await s.commit()
            await bump_stats(s, job_id, skipped=1)
            log.bind(
                event="clean_skip_unchanged",
                page_id=page_id,
                hash=new_hash[:8],
            ).info("content unchanged — skip refine/chunk")
            return {
                "page_id": page_id,
                "skipped": True,
                "content_hash": new_hash,
            }

        page.title = result.title
        page_posted_at = extract_posted_at(result.raw_html_decoded)
        if page_posted_at is not None:
            page.posted_at = page_posted_at
        page.content_hash = new_hash
        page.status = "CLEANED"
        await s.commit()

        # refined JSON 디버그 보존 (storage/refined/{page_id}/page.json)
        refined_path = storage_paths.refined_path(storage_root, page_id, "page.json")
        refined_path.parent.mkdir(parents=True, exist_ok=True)
        refined_path.write_text(
            __import__("json").dumps(
                {
                    "title": result.title,
                    "method": result.method,
                    "preprocessing_version": VERSION,
                    "source_url": page.url,
                    "discovery_report": (page.storage_paths or {}).get("discovery_report"),
                    "attachments": [
                        {
                            "file_name": a.file_name,
                            "source_url": a.source_url,
                            "mime_type": a.mime_type,
                        }
                        for a in attachments
                    ],
                    "body_text": result.body_text,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        log.bind(
            event="clean_ok",
            page_id=page_id,
            method=result.method,
            body_len=len(result.body_text),
            title_len=len(result.title or ""),
            hash=new_hash[:8],
        ).info("cleaned")

        _, url_hash = normalize_url(page.url)
        return {
            "page_id": page_id,
            "url_hash": url_hash,
            "title": result.title,
            "body_text": result.body_text,
            "content_hash": new_hash,
            "method": result.method,
            "skipped": False,
        }
