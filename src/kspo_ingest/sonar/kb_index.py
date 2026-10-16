"""SONAR가 관리하는 Qdrant 인덱스(kspo-3large) 멱등성 유틸.

`trigger_scrape_single` 재실행은 같은 kb_id라도 Qdrant에 새 point를 추가만 하고
기존 point를 지우지 않아, 매 재색인마다 문서가 복제된다(검색 top-k 오염의 원인).
재스크랩 직전에 해당 kb_id의 기존 point를 purge하여 "replace" 의미를 보장한다.
"""
from __future__ import annotations

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("worker", "kb_index")

# 챗봇이 검색하는 SONAR 관리 컬렉션(coverage.py와 동일 대상).
_QDRANT = "http://sonar-qdrant-1:6333"
_COLLECTION = "kspo-3large"


async def purge_kb_points(kb_id: str) -> int:
    """재스크랩 전 kb_id의 기존 Qdrant point를 삭제. 삭제한 개수를 반환.

    실패해도 예외를 던지지 않는다 — purge 실패로 색인 자체가 끊기면 안 되므로,
    로깅만 하고 0을 반환한다(최악의 경우 중복 1건, 정기 정리로 회수 가능).
    """
    if not kb_id:
        return 0
    flt = {"must": [{"key": "metadata.id", "match": {"value": kb_id}}]}
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{_QDRANT}/collections/{_COLLECTION}/points/count",
                json={"filter": flt, "exact": True},
            )
            n = (r.json().get("result") or {}).get("count", 0)
            if n:
                await c.post(
                    f"{_QDRANT}/collections/{_COLLECTION}/points/delete",
                    json={"filter": flt},
                )
        return n
    except Exception as exc:  # noqa: BLE001 — purge는 best-effort
        log.bind(event="kb_purge_error", kb_id=kb_id, err=str(exc)[:200]).warning(
            "재스크랩 전 purge 실패 — 색인은 계속(중복 가능)"
        )
        return 0
