"""코퍼스 중복(scheme 쌍둥이/구버전 해시) 정리를 위한 순수 로직.

저장된 pages.url_hash는 구/신버전이 섞여 신뢰할 수 없으므로, 현행 normalize_url로
정체성을 재계산해 그룹핑한다. I/O·상태 없음 — DB/Qdrant 작업은 CLI가 담당.
"""
from __future__ import annotations

from dataclasses import dataclass

from kspo_ingest.crawl.url_normalize import normalize_url


@dataclass
class PageRow:
    id: int
    url: str
    scheme: str   # 'http' | 'https'
    depth: int
    status: str


def group_by_identity(rows: list[PageRow]) -> dict[str, list[PageRow]]:
    """현행 normalize_url로 canonical url_hash를 재계산해 hash별로 묶는다."""
    groups: dict[str, list[PageRow]] = {}
    for r in rows:
        _, url_hash = normalize_url(r.url)
        groups.setdefault(url_hash, []).append(r)
    return groups


def select_canonical(group: list[PageRow]) -> PageRow:
    """https > 최저 depth > INDEXED 우선 > 최소 id 순으로 canonical 선정."""
    def key(r: PageRow) -> tuple[int, int, int, int]:
        return (
            0 if r.scheme == "https" else 1,
            r.depth,
            0 if r.status == "INDEXED" else 1,
            r.id,
        )
    return sorted(group, key=key)[0]


def find_duplicate_groups(
    rows: list[PageRow],
) -> list[tuple[PageRow, list[PageRow]]]:
    """그룹 크기>1인 것만 (canonical, [제거 대상...]) 튜플로 반환."""
    out: list[tuple[PageRow, list[PageRow]]] = []
    for group in group_by_identity(rows).values():
        if len(group) > 1:
            canon = select_canonical(group)
            losers = [r for r in group if r.id != canon.id]
            out.append((canon, losers))
    return out
