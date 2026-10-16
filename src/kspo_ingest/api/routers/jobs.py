from __future__ import annotations

from urllib.parse import urlsplit

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import AdminDep, SessionDep
from kspo_ingest.api.rate_limit import rate_limit_60_per_minute
from kspo_ingest.api.schemas.job import JobOut, RefreshUrlOut, RefreshUrlRequest
from kspo_ingest.crawl.url_normalize import normalize_url
from kspo_ingest.db.models import CrawlJob, Domain
from kspo_ingest.settings import settings
from kspo_ingest.tasks.jobs import empty_stats
from kspo_ingest.tasks.pipeline.helpers import get_or_create_page

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


_arq_pool = None


async def _get_pool():
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq_pool


@router.post("/full/{domain_id}", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def trigger_full_job(
    domain_id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> CrawlJob:
    return await _trigger_job(s, domain_id=domain_id, job_type="full", arq_function="enqueue_seeds")


@router.post(
    "/incremental/{domain_id}",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_incremental_job(
    domain_id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> CrawlJob:
    return await _trigger_job(
        s, domain_id=domain_id, job_type="incremental", arq_function="run_incremental"
    )


@router.post(
    "/refresh-url",
    response_model=RefreshUrlOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_60_per_minute)],
)
async def trigger_refresh_url(
    body: RefreshUrlRequest,
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> RefreshUrlOut:
    from kspo_ingest.crawl.start_url import parse_start_url

    try:
        normalized, _ = normalize_url(parse_start_url(body.url))
        host = _extract_host(normalized)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid URL") from None

    # Resolve the actual host before looking up the domain-scoped page identity.
    created_domain = False
    domain = (await s.execute(select(Domain).where(Domain.host == host))).scalar_one_or_none()
    if domain is None:
        domain = Domain(host=host, scheme=urlsplit(normalized).scheme, display_name=host)
        s.add(domain)
        await s.commit()
        await s.refresh(domain)
        created_domain = True
    elif not domain.is_active:
        domain.is_active = True
        await s.commit()
    page = await get_or_create_page(s, domain_id=domain.id, url=normalized, depth=0)

    job = CrawlJob(
        domain_id=page.domain_id,
        job_type="url_refresh",
        seed_urls=[normalized],
        status="PENDING",
        triggered_by="admin",
        stats=empty_stats(),
    )
    s.add(job)
    await s.commit()
    await s.refresh(job)

    pool = await _get_pool()
    arq_job = await pool.enqueue_job(
        "refresh_url", job_id=job.id, page_id=page.id, force=body.force
    )
    job.arq_job_id = arq_job.job_id if arq_job else None
    await s.commit()
    return RefreshUrlOut(
        job_id=job.id,
        page_id=page.id,
        arq_job_id=job.arq_job_id,
        created_domain=created_domain,
    )


def _extract_host(raw: str) -> str:
    """사용자 입력(도메인 또는 URL)에서 host만 추출. 소문자·포트/경로 제거.

    'https://www.x.kr/a?b=1' → 'www.x.kr', 'WWW.X.KR' → 'www.x.kr'.
    host를 뽑을 수 없으면 ValueError.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty input")
    # scheme 없이 'www.x.kr/path'로 들어오면 urlsplit이 host를 못 잡으므로 보강.
    if "//" not in text:
        text = "//" + text
    host = urlsplit(text).hostname
    if not host:
        raise ValueError(f"cannot extract host from: {raw!r}")
    return host.lower()


class CrawlRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4096)
    job_type: str = Field(default="full", pattern="^(full|incremental)$")


class CrawlOut(BaseModel):
    job: JobOut
    domain_host: str
    created: bool  # 신규 도메인 자동 등록 여부


@router.post("/crawl", response_model=CrawlOut, status_code=status.HTTP_201_CREATED)
async def trigger_crawl_by_host(
    body: CrawlRequest, s: AsyncSession = SessionDep, _admin: str = AdminDep
) -> CrawlOut:
    """도메인(또는 URL) 입력 → 미등록이면 자동 등록 후 크롤 잡 실행."""
    try:
        from kspo_ingest.crawl.start_url import parse_start_url

        start_url = parse_start_url(body.input)
        host = _extract_host(start_url)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "유효한 도메인이 아닙니다"
        ) from None

    domain = (await s.execute(select(Domain).where(Domain.host == host))).scalar_one_or_none()

    created = False
    if domain is None:
        domain = Domain(host=host, scheme=urlsplit(start_url).scheme, display_name=host)
        s.add(domain)
        await s.commit()
        await s.refresh(domain)
        created = True
    elif not domain.is_active:
        # 비활성 도메인은 크롤 전에 재활성화 (_trigger_job이 inactive를 404 처리).
        domain.is_active = True
        await s.commit()
        await s.refresh(domain)

    arq_function = "enqueue_seeds" if body.job_type == "full" else "run_incremental"
    job = await _trigger_job(
        s,
        domain_id=domain.id,
        job_type=body.job_type,
        arq_function=arq_function,
        seed_urls=[start_url],
    )
    return CrawlOut(job=JobOut.model_validate(job), domain_host=host, created=created)


async def _trigger_job(
    s: AsyncSession,
    *,
    domain_id: int,
    job_type: str,
    arq_function: str,
    seed_urls: list[str] | None = None,
) -> CrawlJob:
    domain = await s.get(Domain, domain_id)
    if domain is None or not domain.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "domain not found or inactive")

    job = CrawlJob(
        domain_id=domain_id,
        job_type=job_type,
        seed_urls=seed_urls,
        status="PENDING",
        triggered_by="admin",
        stats=empty_stats(),
    )
    s.add(job)
    await s.commit()
    await s.refresh(job)

    pool = await _get_pool()
    arq_job = await pool.enqueue_job(arq_function, job_id=job.id, domain_id=domain_id)
    job.arq_job_id = arq_job.job_id if arq_job else None
    await s.commit()
    await s.refresh(job)
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    domain_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    s: AsyncSession = SessionDep,
    _admin: str = AdminDep,
) -> list[CrawlJob]:
    q = select(CrawlJob).order_by(CrawlJob.id.desc()).limit(limit).offset(offset)
    if domain_id is not None:
        q = q.where(CrawlJob.domain_id == domain_id)
    if status_filter is not None:
        q = q.where(CrawlJob.status == status_filter)
    rows = (await s.execute(q)).scalars().all()
    return list(rows)


@router.get("/{id}", response_model=JobOut)
async def get_job(id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep) -> CrawlJob:
    job = await s.get(CrawlJob, id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job


@router.post("/{id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_job(id: int, s: AsyncSession = SessionDep, _admin: str = AdminDep) -> Response:
    job = await s.get(CrawlJob, id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    if job.status not in ("PENDING", "RUNNING"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is already {job.status}")
    job.status = "CANCELLED"
    from datetime import UTC, datetime

    job.finished_at = datetime.now(UTC)
    await s.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class IngestVideosRequest(BaseModel):
    max_videos: int = Field(default=699, ge=1, le=699)


@router.post("/ingest-videos", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest_videos(
    body: IngestVideosRequest,
    _admin: str = AdminDep,
) -> dict:
    """국민체력100 운동처방 동영상 파이프라인 수동 트리거."""
    pool = await _get_pool()
    arq_job = await pool.enqueue_job("ingest_videos", max_videos=body.max_videos)
    return {"job_id": arq_job.job_id if arq_job else None, "max_videos": body.max_videos}
