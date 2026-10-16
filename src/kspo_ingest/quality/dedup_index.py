"""dedup_index — SONAR Qdrant 인덱스의 재색인 중복을 주기적으로 제거.

`trigger_scrape_single`이 비동기 큐로 실행되므로, purge_kb_points(재스크랩 전
삭제)만으로는 여러 scrape가 같은 kb_id에 point를 추가하는 경쟁을 완전히 막지
못한다. 이 크론이 최종 안전망 — 같은 (source, chunk_index)에 내용이 완전히
동일한(md5 일치) point가 2개 이상이면 1개만 남기고 나머지를 point-id로 삭제한다.

무손실: 내용이 다르면 건드리지 않는다. 읽기 후 point-id 지정 삭제라 오삭제 불가.
"""
from __future__ import annotations

import hashlib

import httpx

from kspo_ingest.observability.logger import get_logger

log = get_logger("worker", "dedup_index")

_QDRANT = "http://sonar-qdrant-1:6333"
_COLLECTION = "kspo-3large"


def _scroll_all() -> dict[tuple, list]:
    """(source, chunk_index) → [(point_id, content_md5)] 전수 수집."""
    groups: dict[tuple, list] = {}
    nxt = None
    while True:
        body: dict = {
            "limit": 1000,
            "with_payload": ["metadata.source", "metadata.chunk_index", "page_content"],
        }
        if nxt:
            body["offset"] = nxt
        r = httpx.post(
            f"{_QDRANT}/collections/{_COLLECTION}/points/scroll", json=body, timeout=90
        ).json()["result"]
        for p in r["points"]:
            md = p["payload"].get("metadata") or {}
            h = hashlib.md5((p["payload"].get("page_content") or "").encode()).hexdigest()
            groups.setdefault((md.get("source"), md.get("chunk_index")), []).append((p["id"], h))
        nxt = r.get("next_page_offset")
        if not nxt:
            break
    return groups


async def dedup_index(ctx: dict | None = None) -> dict:
    """중복(동일 source+chunk+내용) point 제거. 반환: 삭제 개수 등."""
    groups = _scroll_all()
    del_ids: list = []
    unsafe = 0
    for _, pts in groups.items():
        if len(pts) < 2:
            continue
        hashes = {h for _, h in pts}
        if len(hashes) == 1:  # 내용 완전 동일 → 1개 유지, 나머지 삭제
            del_ids.extend(pid for pid, _ in pts[1:])
        else:
            unsafe += 1  # 내용 상이 → 안전상 스킵
    removed = 0
    if del_ids:
        with httpx.Client(timeout=90) as c:
            for i in range(0, len(del_ids), 300):
                batch = del_ids[i : i + 300]
                c.post(
                    f"{_QDRANT}/collections/{_COLLECTION}/points/delete",
                    json={"points": batch},
                ).raise_for_status()
                removed += len(batch)
    log.bind(
        event="dedup_index_done",
        groups=len(groups),
        removed=removed,
        content_conflict_skipped=unsafe,
    ).info("index dedup complete")
    return {"removed": removed, "skipped_conflict": unsafe}
