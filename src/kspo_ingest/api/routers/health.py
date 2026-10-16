from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from kspo_ingest.db.engine import make_engine
from kspo_ingest.db.session import async_session
from kspo_ingest.observability.cost_monitor import get_monthly_cost_krw
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.qdrant.bootstrap import ensure_collection
from kspo_ingest.qdrant.client import get_mode
from kspo_ingest.settings import settings

router = APIRouter()
log = get_logger("api", "health")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine(settings)
    return _engine


@router.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    db_ok = await _ping_pg()
    qdrant_status = await _check_qdrant()
    cost_info = await _read_cost() if db_ok else {
        "monthly_cost_krw": "0",
        "monthly_budget_krw": settings.openai_monthly_budget_krw,
        "budget_used_pct": 0.0,
    }
    payload = {
        "db": "ok" if db_ok else "fail",
        "redis": "stub",
        "qdrant_dim": qdrant_status["dim"],
        "qdrant_mode": qdrant_status["mode"],
        "proxy_configured": bool(settings.https_proxy),
        **cost_info,
    }
    if not db_ok or not qdrant_status["healthy"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


async def _read_cost() -> dict:
    """이번 달 누계 + 한도 + 사용률. PG 미가용 시 호출자가 stub로 대체."""
    try:
        async with async_session() as s:
            cost = await get_monthly_cost_krw(s)
        budget = settings.openai_monthly_budget_krw
        used_pct = float(cost / Decimal(budget) * 100) if budget > 0 else 0.0
        return {
            "monthly_cost_krw": str(cost),
            "monthly_budget_krw": budget,
            "budget_used_pct": round(used_pct, 2),
        }
    except Exception as e:  # noqa: BLE001
        log.bind(event="readyz_cost_fail").warning(str(e))
        return {
            "monthly_cost_krw": "0",
            "monthly_budget_krw": settings.openai_monthly_budget_krw,
            "budget_used_pct": 0.0,
        }


async def _ping_pg() -> bool:
    try:
        engine = _get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        log.bind(event="readyz_pg_fail").warning(str(e))
        return False


async def _check_qdrant() -> dict:
    """차원 검증 결과를 /readyz에 노출. 미가용 / dim 불일치 → healthy=False → 503."""
    try:
        st = await ensure_collection()
        return {
            "healthy": st.healthy,
            "dim": st.dim if st.healthy else 0,
            "mode": st.mode,
        }
    except Exception as e:
        log.bind(event="readyz_qdrant_fail").warning(str(e))
        return {"healthy": False, "dim": 0, "mode": get_mode()}
