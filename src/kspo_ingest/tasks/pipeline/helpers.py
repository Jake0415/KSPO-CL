"""ARQ task helpers — DB upsert, storage save, page status transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.crawl import storage
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import Domain, Page


async def get_or_create_page(
    s: AsyncSession,
    *,
    domain_id: int,
    url: str,
    depth: int,
    board_source_id: int | None = None,
    posted_at: datetime | None = None,
) -> Page:
    normalized, url_hash = normalize_url(url)
    existing = (
        await s.execute(select(Page).where(Page.domain_id == domain_id, Page.url_hash == url_hash))
    ).scalar_one_or_none()
    if existing is not None:
        changed = False
        if posted_at is not None and existing.posted_at is None:
            existing.posted_at = posted_at
            changed = True
        if board_source_id is not None and existing.board_source_id is None:
            existing.board_source_id = board_source_id
            changed = True
        if changed:
            await s.commit()
        return existing

    page = Page(
        domain_id=domain_id,
        url=normalized,
        url_hash=url_hash,
        status="DISCOVERED",
        depth=depth,
        board_source_id=board_source_id,
        posted_at=posted_at,
    )
    s.add(page)
    await s.commit()
    await s.refresh(page)
    return page


async def mark_fetched(
    s: AsyncSession, page_id: int, *, http_status: int, content_type: str | None
) -> None:
    page = await s.get(Page, page_id)
    if page is None:
        return
    page.http_status = http_status
    page.last_http_status = http_status
    page.content_type = content_type
    page.status = "FETCHED"
    page.last_fetched_at = datetime.now(UTC)
    page.error_count = 0
    await s.commit()


async def mark_error(s: AsyncSession, page_id: int, *, error: str) -> None:
    page = await s.get(Page, page_id)
    if page is None:
        return
    page.status = "ERROR"
    page.storage_paths = {**(page.storage_paths or {}), "last_processing_error": error[:500]}
    page.error_count = (page.error_count or 0) + 1
    page.last_fetched_at = datetime.now(UTC)
    await s.commit()


async def mark_dropped(s: AsyncSession, page_id: int, *, reason: str) -> None:
    page = await s.get(Page, page_id)
    if page is None:
        return
    page.status = "DROPPED"
    page.drop_reason = reason
    await s.commit()


async def mark_refined(
    s: AsyncSession, page_id: int, *, content_hash: str, title: str | None
) -> None:
    page = await s.get(Page, page_id)
    if page is None:
        return
    page.status = "REFINED"
    page.content_hash = content_hash
    if title:
        page.title = title
    await s.commit()


async def get_domain(s: AsyncSession, domain_id: int) -> Domain | None:
    return await s.get(Domain, domain_id)


def save_raw(storage_root: Path, domain_id: int, url_hash: str, body: bytes) -> Path:
    path = storage.raw_path(storage_root, domain_id, url_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return path
