from __future__ import annotations

from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.api.schemas.domain import DomainCreate, DomainOut, DomainUpdate
from kspo_ingest.crawl.family_sitemap import extract_family_hosts
from kspo_ingest.db.models import Domain
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.adapter import QdrantDirectAdapter
from kspo_ingest.settings import settings
from kspo_ingest.tasks.pipeline.orphan import handle_domain_deactivation

router = APIRouter(prefix="/api/domains", tags=["domains"])
log = get_logger("api", "domains")


@router.get("", response_model=list[DomainOut])
async def list_domains(s: AsyncSession = SessionDep, _admin: str = AdminDep) -> list[Domain]:
    rows = (await s.execute(select(Domain).order_by(Domain.id))).scalars().all()
    return list(rows)


@router.post("", response_model=DomainOut, status_code=status.HTTP_201_CREATED)
async def create_domain(
    body: DomainCreate, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> Domain:
    if body.start_url:
        from urllib.parse import urlsplit

        if urlsplit(body.start_url).hostname != body.host:
            raise HTTPException(422, "Start URL must match domain")
    d = Domain(**body.model_dump())
    s.add(d)
    try:
        await s.commit()
    except IntegrityError:
        await s.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "host already exists") from None
    await s.refresh(d)
    return d


@router.get("/{id}", response_model=DomainOut)
async def get_domain(id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep) -> Domain:
    d = await s.get(Domain, id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "domain not found")
    return d


@router.patch("/{id}", response_model=DomainOut)
async def update_domain(
    id: int, body: DomainUpdate, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> Domain:
    d = await s.get(Domain, id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "domain not found")
    patch = body.model_dump(exclude_unset=True)
    deactivating = "is_active" in patch and patch["is_active"] is False and d.is_active is True
    if patch.get("start_url"):
        from urllib.parse import urlsplit

        from kspo_ingest.crawl.start_url import parse_start_url

        try:
            patch["start_url"] = parse_start_url(patch["start_url"])
            if urlsplit(patch["start_url"]).hostname != d.host:
                raise ValueError("Start URL must match domain")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    for k, v in patch.items():
        setattr(d, k, v)
    d.updated_at = datetime.now(UTC)
    await s.commit()
    await s.refresh(d)

    if deactivating:
        # is_active true → false 전환 — Qdrant 청크 정리 + 페이지 일괄 REMOVED.
        try:
            removed = await handle_domain_deactivation(s, domain=d)
            log.bind(
                event="domain_deactivated",
                host=d.host,
                qdrant_removed=removed,
            ).info("domain deactivated")
        except Exception as exc:  # noqa: BLE001
            log.bind(
                event="domain_deactivated_fail",
                host=d.host,
                error=type(exc).__name__,
            ).warning(str(exc))
    return d


async def _fetch_kspo_main_html() -> str:
    """Fetch KSPO main page HTML for family site discovery.

    루트(``/``)를 크롤러 기본 UA로 요청한다. ``/main.do``는 UA 없는 요청에
    ``/cmmn/error.jsp`` 리다이렉트 stub(402B)만 반환해 패밀리 링크 추출이 불가하다.
    """
    headers = {"User-Agent": settings.crawl_user_agent_default}
    async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
        r = await client.get("https://www.kspo.or.kr/")
        r.raise_for_status()
        return r.text


@router.post("/discover-family")
async def discover_family(s: AsyncSession = SessionDep, _admin: str = AdminDep) -> dict:
    """Discover and auto-register KSPO family site domains."""
    html = await _fetch_kspo_main_html()
    hosts = extract_family_hosts(html)

    created = 0
    skipped = 0
    for host in hosts:
        existing = await s.execute(select(Domain).where(Domain.host == host))
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue
        domain = Domain(host=host, scheme="https", display_name=host)
        s.add(domain)
        created += 1
    await s.commit()

    return {"discovered": len(hosts), "created": created, "skipped": skipped}


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep) -> Response:
    d = await s.get(Domain, id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "domain not found")
    host = d.host
    await s.delete(d)
    await s.commit()
    try:
        deleted = await QdrantDirectAdapter().delete_by_domain(host)
        log.bind(event="domain_delete_qdrant", host=host, deleted=deleted).info(
            "qdrant payload purged"
        )
    except Exception as exc:  # noqa: BLE001
        log.bind(event="domain_delete_qdrant_fail", host=host, error=type(exc).__name__).warning(
            str(exc)
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
