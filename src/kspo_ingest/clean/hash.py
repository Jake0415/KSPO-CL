from __future__ import annotations

import hashlib
import re

_RE_WHITESPACE = re.compile(r"\s+")
_RE_VIEW_COUNT = re.compile(r"\s*조회수\s*[:：]?\s*[\d,]+")
_RE_TODAY = re.compile(r"\s*오늘\s*날짜\s*[:：]?\s*\S*")


def normalize_for_hash(text: str) -> str:
    """변경 감지용 안정적 hash. content_hash로 page에 저장.

    조회수·오늘 날짜처럼 의미상 동일하지만 매 요청마다 다른 표시는 제거.
    """
    s = _RE_WHITESPACE.sub(" ", text).strip()
    s = _RE_VIEW_COUNT.sub("", s)
    s = _RE_TODAY.sub("", s)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
