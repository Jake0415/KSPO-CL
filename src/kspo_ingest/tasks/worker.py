"""ARQ WorkerSettings — 컨테이너 entry: `arq kspo_ingest.tasks.worker.WorkerSettings`."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from arq import cron
from arq.connections import RedisSettings
from redis.asyncio import Redis

from kspo_ingest.crawl.browser import BrowserFetcher
from kspo_ingest.crawl.checkpoint import CheckpointManager
from kspo_ingest.crawl.domain_profile import DomainProfiler
from kspo_ingest.crawl.fetcher import Fetcher
from kspo_ingest.crawl.frontier import Frontier
from kspo_ingest.crawl.proxy import ProxyRotator
from kspo_ingest.crawl.rate_limit import HostRateLimit
from kspo_ingest.crawl.readiness import ReadinessPolicy
from kspo_ingest.crawl.robots import RobotsCache
from kspo_ingest.crawl.selector import AdaptiveSelector
from kspo_ingest.crawl.session_mgr import SessionManager
from kspo_ingest.crawl.smart_fetcher import SmartFetcher
from kspo_ingest.db.session import async_session
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.platform.plugins import plugin_manager
from kspo_ingest.quality.coverage import run_coverage
from kspo_ingest.quality.dedup_index import dedup_index
from kspo_ingest.settings import settings
from kspo_ingest.sonar.client import SonarClient
from kspo_ingest.tasks.cron import (
    archive_expired_board_posts,
    archive_expired_documents,
    auto_register_daily_boards,
    daily_board_refresh,
    monthly_full_all,
    refresh_stats_views,
)
from kspo_ingest.tasks.cron_alerts import check_budget_alerts
from kspo_ingest.tasks.cron_kpi import cron_kpi_daily
from kspo_ingest.tasks.jobs import sweep_stale_jobs
from kspo_ingest.tasks.pipeline.browser_harvest import browser_harvest
from kspo_ingest.tasks.pipeline.chunk_and_index import chunk_and_index
from kspo_ingest.tasks.pipeline.clean_page import clean_page
from kspo_ingest.tasks.pipeline.enqueue_seeds import enqueue_seeds
from kspo_ingest.tasks.pipeline.extract_links import extract_links
from kspo_ingest.tasks.pipeline.fetch_page import fetch_page
from kspo_ingest.tasks.pipeline.ingest_videos import ingest_videos
from kspo_ingest.tasks.pipeline.refine_page import refine_page
from kspo_ingest.tasks.pipeline.refresh_url import refresh_url
from kspo_ingest.tasks.pipeline.run_board_refresh import run_board_refresh
from kspo_ingest.tasks.pipeline.run_incremental import run_incremental
from kspo_ingest.tasks.pipeline.run_uncollected_backfill import run_uncollected_backfill

log = get_logger("worker", "settings")


async def on_startup(ctx: dict) -> None:
    redis = Redis.from_url(settings.redis_url)

    # 세션 매니저 — 커넥션 풀 재사용
    session_mgr = SessionManager()

    # 프록시 로테이션
    proxy_urls = [u.strip() for u in settings.proxy_urls.split(",") if u.strip()]
    proxy_rotator = ProxyRotator(proxy_urls) if proxy_urls else ProxyRotator()

    # Fetcher — 세션 매니저 주입
    fetcher = Fetcher(session_manager=session_mgr)

    # Browser fetcher — stealth + 범용 설정
    browser_fetcher = BrowserFetcher(
        default_profile=settings.stealth_profile or None,
        headless=True,
        dynamic_max_actions=settings.crawl_dynamic_max_actions,
        readiness_policy=ReadinessPolicy(
            initial_timeout_ms=settings.crawl_initial_ready_timeout_ms,
            action_timeout_ms=settings.crawl_action_ready_timeout_ms,
            stable_ms=settings.crawl_content_stable_ms,
        ),
    )

    # SmartFetcher — 자동 전략 선택 통합 fetcher
    profiler = DomainProfiler()
    smart_fetcher = SmartFetcher(
        http_fetcher=fetcher,
        browser_fetcher=browser_fetcher,
        profiler=profiler,
        render_all_html=settings.crawl_render_all_html,
    )

    ctx["session_factory"] = async_session
    ctx["redis"] = redis
    ctx["session_mgr"] = session_mgr
    ctx["fetcher"] = fetcher
    ctx["playwright_fetcher"] = browser_fetcher  # 하위 호환
    ctx["browser_fetcher"] = browser_fetcher
    ctx["smart_fetcher"] = smart_fetcher
    ctx["domain_profiler"] = profiler
    ctx["robots"] = RobotsCache()
    ctx["frontier"] = Frontier(redis)
    ctx["rate_limit"] = HostRateLimit(redis)
    ctx["storage_root"] = Path(settings.storage_root)
    ctx["proxy_rotator"] = proxy_rotator
    ctx["checkpoint_mgr"] = CheckpointManager(redis)
    ctx["adaptive_selector"] = AdaptiveSelector()

    # SONAR 클라이언트 — 설정이 있는 경우에만 초기화.
    # base_url/email/password/project_id 중 하나라도 비면 push_to_sonar 스텝이 no-op.
    if all(
        [
            settings.sonar_base_url,
            settings.sonar_email,
            settings.sonar_password,
            settings.sonar_project_id,
        ]
    ):
        ctx["sonar_client"] = SonarClient(
            base_url=settings.sonar_base_url,
            email=settings.sonar_email,
            password=settings.sonar_password,
            project_id=settings.sonar_project_id,
            timeout_seconds=settings.sonar_timeout_seconds,
            retry_max=settings.sonar_retry_max,
            retry_backoff_seconds=settings.sonar_retry_backoff_seconds,
        )
        ctx["sonar_namespace"] = settings.sonar_namespace or settings.sonar_project_id

    # 플러그인 로드
    if settings.plugin_modules:
        for mod_path in settings.plugin_modules.split(","):
            mod_path = mod_path.strip()
            if mod_path:
                plugin_manager.load_module(mod_path)

    # 유령 job 정리: kill -9/OOM/컨테이너 재생성으로 job_guard가 못 돈 경우의 안전망.
    # job_timeout보다 오래 RUNNING인 잡을 FAILED로 전환한다.
    async with async_session() as s:
        swept = await sweep_stale_jobs(s, older_than_seconds=WorkerSettings.job_timeout)
    if swept:
        log.bind(event="stale_jobs_swept", count=swept).warning("stale jobs → FAILED")

    log.bind(
        event="worker_started",
        redis_url=settings.redis_url,
        proxies=len(proxy_urls),
        stealth=settings.stealth_profile or "none",
        plugins=plugin_manager.plugin_names,
    ).info("worker startup")
    log.bind(
        event="cron_registered",
        cron_count=0 if settings.app_env == "local" else 11,
        monthly_full="1st 02:00 (container TZ)",
        stats_refresh="every 5min",
        budget_alerts="every 1min",
        kpi_daily="00:30 (container TZ)",
    ).info("cron registered")


async def on_shutdown(ctx: dict) -> None:
    redis: Redis | None = ctx.get("redis")
    if redis is not None:
        await redis.aclose()

    # 브라우저 fetcher 정리
    browser: BrowserFetcher | None = ctx.get("browser_fetcher")
    if browser is not None:
        await browser.close()

    # SONAR 클라이언트 정리 (httpx AsyncClient 소유)
    sonar: SonarClient | None = ctx.get("sonar_client")
    if sonar is not None:
        await sonar.close()

    # SmartFetcher 정리 (http + browser 모두 정리)
    smart: SmartFetcher | None = ctx.get("smart_fetcher")
    if smart is not None:
        await smart.close()
    else:
        # fallback: 개별 정리
        fetcher: Fetcher | None = ctx.get("fetcher")
        if fetcher is not None:
            await fetcher.close()

    log.bind(event="worker_stopped").info("worker shutdown")


class WorkerSettings:
    timezone = ZoneInfo("Asia/Seoul")
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [
        enqueue_seeds,
        fetch_page,
        clean_page,
        refine_page,
        extract_links,
        chunk_and_index,
        run_incremental,
        run_board_refresh,
        run_uncollected_backfill,
        refresh_url,
        ingest_videos,
        browser_harvest,
        run_coverage,
        dedup_index,
    ]
    # queue_name 미지정 — ARQ 기본 `arq:queue` 사용. API의 enqueue_job도 동일 기본값 사용.
    cron_jobs = [
        # 매월 1일 02:00 KST — active 도메인 전체 full 크롤(enqueue_seeds).
        cron(
            monthly_full_all,
            day={1},
            hour={2},
            minute={0},
            run_at_startup=False,
        ),
        # 5분 주기 — :00, :05, :10, ... :55
        cron(
            refresh_stats_views,
            minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=False,
        ),
        # 분 단위 — 월 누계 80% 임계 검사 (PRD §7.1). Redis 키로 같은 달 1회만 SMTP 발신.
        cron(
            check_budget_alerts,
            minute=set(range(60)),
            run_at_startup=False,
        ),
        # 매일 00:30 KST — KPI 4종 snapshot 1+N행 (전체 + 활성 도메인별).
        cron(
            cron_kpi_daily,
            hour={0},
            minute={30},
            run_at_startup=False,
        ),
        # 매일 04:00 KST — confirmed board_source 도메인의 board Job enqueue.
        cron(
            daily_board_refresh,
            hour={4},
            minute={0},
            run_at_startup=False,
        ),
        # 매일 06:00 KST — 세션/JS 게이트 게시판(sqms 등) 클릭 하베스트.
        cron(
            browser_harvest,
            hour={6},
            minute={0},
            run_at_startup=False,
        ),
        # 매일 07:00 KST — 게시판 커버리지 검증(누락 자동 감지).
        cron(
            run_coverage,
            hour={7},
            minute={0},
            run_at_startup=False,
        ),
        # 매일 07:30 KST — 인덱스 재색인 중복 제거(harvest/refresh 이후 최종 정리).
        cron(
            dedup_index,
            hour={7},
            minute={30},
            run_at_startup=False,
        ),
        # 매일 05:00 KST — freshness 만료 문서 archive 전환.
        cron(
            archive_expired_documents,
            hour={5},
            minute={0},
            run_at_startup=True,  # 배포 기동 즉시 1회 소급 스윕(멱등)
        ),
        # 매일 05:30 KST — posted_at 만료 게시글을 kspo_archive로 이동.
        cron(
            archive_expired_board_posts,
            hour={5},
            minute={30},
            run_at_startup=False,
        ),
        # 매주 월 03:30 KST — 빈도 실측으로 DAILY 게시판 자동 confirmed 등록.
        cron(
            auto_register_daily_boards,
            weekday={0},
            hour={3},
            minute={30},
            run_at_startup=False,
        ),
    ]
    max_jobs = 4
    max_tries = 5
    # 대형 도메인 full 크롤(수백~수천 페이지 × LLM 정제+임베딩)은 1시간을 초과한다.
    # 초과 시 ARQ가 CancelledError로 잡을 죽이고 job_guard가 FAILED 처리하지만,
    # 크롤이 중간에 잘리므로 넉넉히 상향(6시간). 필요 시 settings로 조정.
    job_timeout = getattr(settings, "job_timeout_seconds", None) or 21600  # 6h
    on_startup = on_startup
    on_shutdown = on_shutdown
