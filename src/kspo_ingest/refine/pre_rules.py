from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DropReason = Literal["too_short", "error_page", "empty_list", "english_majority"]

ERROR_TITLES = frozenset(
    {"로그인", "오류", "404", "page not found", "에러", "오류 페이지", "not found"}
)

# 목록/게시판이 행을 하나도 렌더하지 못한 상태 — 본문 없이 머리글·안내문만 남는다.
# 이런 페이지도 300자 안팎이라 too_short(10자)를 통과해 Q1으로 적재되므로,
# KB에 내용 없는 문서가 쌓여 검색을 오염시킨다. 별도 룰로 차단한다.
EMPTY_LIST_PHRASES: tuple[str, ...] = (
    "자료가 없습니다",
    "게시물이 없습니다",
    "등록된 게시물이 없습니다",
    "검색된 결과가 없습니다",
    "검색결과가 없습니다",
    "데이터가 없습니다",
    "조회된 자료가 없습니다",
)

# 위 문구가 본문의 대부분을 차지할 때만 드롭한다. 실제 콘텐츠 페이지가 안내 문구를
# 인용하는 경우를 오드롭하지 않기 위한 상한.
EMPTY_LIST_MAX_LEN = 1000

# eGov 목록의 "( n/N Pages )" 표기. n > N이면 범위를 벗어난 페이지네이션이며
# 본문은 빈 목록이다. KSPO 게시판에서 pageIndex를 초과 생성해 같은 제목의 빈 문서가
# 대량 적재되던 문제(대상사업 목록 p4~p11)를 여기서 끊는다.
_PAGE_OF_RE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,4})\s*Pages", re.IGNORECASE)

# "총  건의 게시물" 처럼 건수 자리가 비어 있으면 목록이 렌더되지 않은 것이다
# (JS/AJAX로 채우는 화면을 정적 fetch한 경우).
_EMPTY_COUNT_RE = re.compile(r"총\s*건의\s*게시물")


@dataclass
class PreCheckResult:
    drop: bool
    reason: DropReason | None


def _is_empty_list(body_text: str) -> bool:
    """목록이 행을 하나도 렌더하지 못한 페이지인지 판정."""
    # (a) "( 10/3 Pages )" — 범위를 벗어난 페이지네이션
    for cur, total in _PAGE_OF_RE.findall(body_text):
        if int(cur) > int(total):
            return True

    # (b) "총  건의 게시물" — 건수 자리가 비어 있음(JS 미렌더)
    if _EMPTY_COUNT_RE.search(body_text):
        return True

    # (c) "자료가 없습니다" 류 안내문이 짧은 본문의 대부분을 차지
    if len(body_text) <= EMPTY_LIST_MAX_LEN:
        return any(p in body_text for p in EMPTY_LIST_PHRASES)

    return False


ENGLISH_EXCLUSION_THRESHOLD = 0.9


def english_ratio(body_text: str) -> float:
    """English alphabet share among Unicode letters, excluding technical references."""
    text = re.sub(r"https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "", body_text)
    text = re.sub(
        r"[^\s/]+\.(?:pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip|jpg|png)(?!\w)",
        "",
        text,
        flags=re.I,
    )
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    return sum("a" <= char.lower() <= "z" for char in letters) / len(letters)


def check(body_text: str, title: str | None, *, ko_ratio_threshold: float) -> PreCheckResult:
    """Exclude <10 characters, error pages and empty lists.

    ko_ratio_threshold is retained for caller compatibility and intentionally ignored.
    """
    if len(body_text.strip()) < 10:
        return PreCheckResult(drop=True, reason="too_short")

    if title:
        normalized = title.strip().lower()
        if normalized in {t.lower() for t in ERROR_TITLES}:
            return PreCheckResult(drop=True, reason="error_page")

    if _is_empty_list(body_text):
        return PreCheckResult(drop=True, reason="empty_list")

    if english_ratio(body_text) >= ENGLISH_EXCLUSION_THRESHOLD:
        return PreCheckResult(drop=True, reason="english_majority")

    return PreCheckResult(drop=False, reason=None)
