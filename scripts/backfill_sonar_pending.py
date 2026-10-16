"""backfill_sonar_pending — SONAR mongo에 status:-1로 방치된 KB 문서 일괄 트리거.

이번 세션에서 확인된 issue:
- push_to_sonar가 POST /kb만 하고 /kb/scrape/single 트리거를 안 했다 (b 커밋에서 수정).
- 그 결과 이번 세션 이전에 push된 KB들이 mongo에 status:-1로 방치돼 Qdrant 색인 안 됨.
- namespace.hybrid=false로 전환된 상태(2026-07-31)에서 scrape/single 트리거하면
  non-hybrid tiledesk-trainer 큐로 흘러 정상 인덱싱된다.

사용:
    docker compose -f docker/docker-compose.yml exec -T api \
        python scripts/backfill_sonar_pending.py

옵션 env:
    BATCH_LIMIT (기본 5000) — 한 실행에 처리할 최대 KB 수
    THROTTLE_MS (기본 200) — 각 trigger 간 지연 밀리초 (SONAR 부하 제어)
"""
from __future__ import annotations

import asyncio
import os

import httpx

from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings
from kspo_ingest.sonar.client import SonarClient, SonarError

log = get_logger("cli", "backfill_sonar_pending")

BATCH_LIMIT = int(os.environ.get("BATCH_LIMIT", "5000"))
THROTTLE_MS = int(os.environ.get("THROTTLE_MS", "200"))


async def _list_pending_kb_ids(client: SonarClient) -> list[str]:
    """SONAR /kb?status=-1&namespace=... 로 대기중 KB id 수집."""
    token = await client._get_token()
    url = (
        f"{settings.sonar_base_url}/api/{settings.sonar_project_id}/kb"
        f"?status=-1&namespace={settings.sonar_namespace}&limit={BATCH_LIMIT}"
    )
    async with httpx.AsyncClient(timeout=60.0) as h:
        r = await h.get(url, headers={"Authorization": token})
        r.raise_for_status()
        data = r.json()
    kbs = data.get("kbs") or []
    return [str(kb["_id"]) for kb in kbs if kb.get("_id")]


async def main() -> None:
    sonar = SonarClient(
        base_url=settings.sonar_base_url,
        email=settings.sonar_email,
        password=settings.sonar_password,
        project_id=settings.sonar_project_id,
    )

    try:
        kb_ids = await _list_pending_kb_ids(sonar)
        total = len(kb_ids)
        log.bind(event="backfill_start", total=total).info(f"pending KBs: {total}")

        ok = 0
        errors = 0
        for i, kb_id in enumerate(kb_ids, start=1):
            try:
                await sonar.trigger_scrape_single(
                    kb_id=kb_id,
                    namespace=settings.sonar_namespace,
                    kb_type="text",
                )
                ok += 1
            except SonarError as exc:
                errors += 1
                log.bind(
                    event="backfill_trigger_error", kb_id=kb_id, err=str(exc)[:200]
                ).warning("trigger failed")
            if i % 50 == 0:
                log.bind(
                    event="backfill_progress",
                    processed=i,
                    total=total,
                    ok=ok,
                    errors=errors,
                ).info(f"progress {i}/{total}")
            if THROTTLE_MS > 0:
                await asyncio.sleep(THROTTLE_MS / 1000)

        log.bind(
            event="backfill_done", total=total, ok=ok, errors=errors
        ).info(f"완료: {ok}/{total} 성공, {errors} 오류")
    finally:
        await sonar.close()


if __name__ == "__main__":
    asyncio.run(main())
