from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware

from kspo_ingest.api.middleware import RequestIdMiddleware
from kspo_ingest.api.routers import (
    alerts,
    auth,
    board_sources,
    console,
    domains,
    files,
    health,
    jobs,
    kpi,
    pages,
    qa,
    qa_logs,
    settings_router,
)
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.platform.metrics import get_metrics_text
from kspo_ingest.qdrant.bootstrap import ensure_all_collections
from kspo_ingest.settings import settings

log = get_logger("api", "startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.bind(
        event="startup_proxy",
        https_proxy=settings.https_proxy or "",
        http_proxy=settings.http_proxy or "",
        no_proxy=settings.no_proxy,
        budget_krw=settings.openai_monthly_budget_krw,
        qdrant_url=settings.qdrant_url,
    ).info("startup")
    if settings.kb_bootstrap == "managed":
        try:
            results = await ensure_all_collections()
            for st in results:
                log.bind(
                    event="qdrant_bootstrap",
                    healthy=st.healthy,
                    dim=st.dim,
                    mode=st.mode,
                ).info("qdrant bootstrap")
        except Exception as exc:  # noqa: BLE001
            log.bind(event="qdrant_bootstrap_fail", error=type(exc).__name__).warning(str(exc))
    yield
    log.bind(event="shutdown").info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="kspo-ingest",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.app_env == "production",
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(domains.router)
    app.include_router(board_sources.router)
    app.include_router(jobs.router)
    app.include_router(alerts.router)
    app.include_router(kpi.router)
    app.include_router(pages.router)
    app.include_router(settings_router.router)
    app.include_router(qa_logs.router)
    app.include_router(console.router)  # RAG Ops Console 집계
    app.include_router(qa.router)  # 인증 없음 — 챗봇 공개 QA
    app.include_router(files.router)  # 인증 없음 — 챗봇 공개 화이트리스트

    @app.get("/metrics", response_class=PlainTextResponse, tags=["system"])
    async def metrics_endpoint():
        return get_metrics_text()

    return app


app = create_app()
