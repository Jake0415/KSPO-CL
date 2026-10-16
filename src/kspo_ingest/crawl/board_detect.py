from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.crawl.board_validation import BoardValidation, entry_url, validate_board
from kspo_ingest.crawl.external_fetch import fetch_external
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import BoardSource, Domain


async def verify_entry(
    url: str,
    domain: Domain,
    *,
    fetcher=None,
    html: str | None = None,
    fetched_url: str | None = None,
) -> BoardValidation:
    entry = entry_url(url, domain.host)
    if entry is None:
        return BoardValidation(False, None, "not_list_url_or_wrong_host")
    # Never validate a first-entry URL using HTML from a detail, later page or search result.
    if html is None or fetched_url != entry:
        if fetcher is not None:
            result = await fetcher.fetch(entry, user_agent=domain.user_agent or "KSPO-Ingest")
        else:
            result = await fetch_external(entry, user_agent=domain.user_agent or "KSPO-Ingest")
        if result.http_status != 200:
            raise ConnectionError("board_entry_http_error")
        actual = getattr(result, "url", None) or entry
        actual_entry = entry_url(actual, domain.host)
        if actual_entry is None or normalize_url(actual_entry)[1] != normalize_url(entry)[1]:
            return BoardValidation(False, entry, "entry_redirected_to_other_content")
        entry = actual_entry
        enc = detect_encoding(result.raw_bytes, result.content_type)
        html = result.raw_bytes.decode(enc, errors="replace")
    return validate_board(html, entry, domain.host)


async def upsert_board_candidate(
    s: AsyncSession,
    *,
    domain_id: int,
    list_url: str,
    html: str | None = None,
    fetched_url: str | None = None,
    fetcher=None,
) -> BoardSource | None:
    domain = await s.get(Domain, domain_id)
    if domain is None:
        return None
    verdict = await verify_entry(
        list_url, domain, html=html, fetched_url=fetched_url, fetcher=fetcher
    )
    if not verdict.valid:
        return None
    existing = (
        await s.execute(
            select(BoardSource).where(
                BoardSource.domain_id == domain_id, BoardSource.list_url == verdict.entry_url
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status != "rejected":
            existing.status = "confirmed"
            existing.validation_error = None
            existing.confirmed_at = datetime.now(UTC)
            await s.commit()
        return existing
    src = BoardSource(
        domain_id=domain_id,
        list_url=verdict.entry_url,
        status="confirmed",
        confirmed_at=datetime.now(UTC),
    )
    s.add(src)
    await s.commit()
    return src


async def revalidate_source(s: AsyncSession, src: BoardSource, domain: Domain, *, fetcher=None):
    verdict = await verify_entry(src.list_url, domain, fetcher=fetcher)
    if not verdict.valid:
        src.status = "invalid"
        src.validation_error = verdict.reason
        await s.commit()
        return None
    # Keep the existing record ID and associations. A canonical duplicate is excluded.
    other = (
        await s.execute(
            select(BoardSource).where(
                BoardSource.domain_id == src.domain_id,
                BoardSource.list_url == verdict.entry_url,
                BoardSource.id != src.id,
            )
        )
    ).scalar_one_or_none()
    if other is not None:
        src.status = "invalid"
        src.validation_error = "duplicate_first_entry"
        await s.commit()
        return None
    src.list_url = verdict.entry_url
    src.status = "confirmed"
    src.confirmed_at = src.confirmed_at or datetime.now(UTC)
    src.validation_error = None
    await s.commit()
    return verdict.entry_url
