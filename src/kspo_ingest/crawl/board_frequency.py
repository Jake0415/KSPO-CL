"""게시판 갱신 빈도 → 티어 분류 (순수 로직)."""
from __future__ import annotations

DAILY_MIN_30D = 3


def classify_board_tier(d30: int, d90: int) -> str:
    """최근 30/90일 신규 게시글 수로 티어 판정."""
    if d30 >= DAILY_MIN_30D:
        return "DAILY"
    if d30 >= 1 or d90 >= 3:
        return "WEEKLY"
    return "STALE"
