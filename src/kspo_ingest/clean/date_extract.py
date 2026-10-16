"""Extract posted_at date from HTML — 발행일 우선, 등록일 fallback."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from selectolax.parser import HTMLParser

_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
_KOR_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
_YY_DATE_RE = re.compile(r"\b(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\b")

# 발행일(게시일) 신호
_PUBLISH_META = [
    'meta[property="article:published_time"]',
    'meta[name="article:published_time"]',
    'meta[property="og:article:published_time"]',
    'meta[name="pubdate"]',
    'meta[name="date"]',
    'meta[name="DC.date"]',
    'meta[name="dcterms.created"]',
]
_PUBLISH_LABELS = ("게시일",)
# 등록일/작성일 fallback 신호
_REGISTERED_SELECTORS = [
    ".date", ".write_date", ".reg_date", ".regdate",
    "span.date", "td.date", ".view_date", ".board_date",
]
_REGISTERED_LABELS = ("작성일자", "등록일자", "작성일", "등록일")


def _valid_or_none(dt: datetime | None) -> datetime | None:
    """미래일자(파싱 오류 정황)는 무효 처리."""
    if dt is None:
        return None
    if dt > datetime.now(UTC):
        return None
    return dt


def _parse_date_str(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        # Ensure timezone-aware for comparison
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (ValueError, TypeError):
        pass
    for rx, base in ((_KOR_DATE_RE, 0), (_DATE_RE, 0), (_YY_DATE_RE, 2000)):
        m = rx.search(text)
        if m:
            try:
                y = int(m.group(1)) + base
                return datetime(y, int(m.group(2)), int(m.group(3)), tzinfo=UTC)
            except ValueError:
                continue
    return None


def _label_date(body_text: str, labels: tuple[str, ...]) -> datetime | None:
    for label in labels:
        idx = body_text.find(label)
        if idx == -1:
            continue
        dt = _parse_date_str(body_text[idx: idx + 40])
        if dt:
            return dt
    return None


def extract_posted_at_with_source(html: str) -> tuple[datetime | None, str]:
    """발행일 우선(published) → 등록일 fallback(registered) → none."""
    if not html:
        return None, "none"
    tree = HTMLParser(html)
    body_text = tree.body.text(separator=" ") if tree.body else ""

    # Pass 1 — 발행일
    for selector in _PUBLISH_META:
        node = tree.css_first(selector)
        if node is not None:
            dt = _valid_or_none(_parse_date_str(node.attributes.get("content", "") or ""))
            if dt:
                return dt, "published"
    dt = _valid_or_none(_label_date(body_text, _PUBLISH_LABELS))
    if dt:
        return dt, "published"

    # Pass 2 — 등록일/작성일 fallback
    for selector in _REGISTERED_SELECTORS:
        node = tree.css_first(selector)
        if node is not None:
            dt = _valid_or_none(_parse_date_str(node.text(separator=" ").strip()))
            if dt:
                return dt, "registered"
    dt = _valid_or_none(_label_date(body_text, _REGISTERED_LABELS))
    if dt:
        return dt, "registered"

    return None, "none"


def extract_posted_at(html: str) -> datetime | None:
    return extract_posted_at_with_source(html)[0]
