"""Generalized URL classification for crawl discovery (engine-level rule).

Shared by EVERY crawler (main-pipeline `internal_links`, CLI `spider`, and the
sports crawler): decides whether a URL is a *non-content* auth/account/utility
endpoint that must never enter the crawl frontier or the knowledge base —
independent of site.

Replaces per-crawler fixed substring lists that missed real-world variants
(`pw_search.do`, `find-id`, camelCase, etc.). Matching is done on normalized
path *segments* (strip extension, drop `-`/`_`, lowercase) so all spelling
variants collapse to one token, while avoiding substring false positives
(`border`≠`order`, `concert`≠`cert`).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# STRONG tokens — unambiguous auth/account strings matched as a *substring* of
# the normalized path, so compounds (memberJoinSelect, findVoucherInfo) also hit.
# Every entry is long/specific enough that no real content word contains it.
_STRONG_TOKENS: tuple[str, ...] = (
    # session / auth
    "login", "loginform", "forlogin", "logout", "signin", "signup", "signout",
    # membership lifecycle
    "memberjoin", "memberwrite", "memberregist", "memberwithdraw",
    "membersecession", "memberleave", "withdraw", "secession",
    # account self-service
    "mypage", "gomypage",
    # NOTE: "findmember" 단독은 제외 — facilityFindMember(시설 수강신청) 같은
    # 콘텐츠 페이지를 오검출한다. 계정복구 의미인 findMemberInfo만 포함.
    "findid", "findpw", "findpwd", "findpassword", "findidpw",
    "findmemberinfo", "findvoucherinfo",
    "pwsearch", "idsearch", "pwfind", "idfind", "pwreset", "pwdreset", "passwd",
    # identity verification (self-cert / NICE) — non-crawlable auth walls
    "checkplus", "checkplusopen", "selfcert", "niceauth", "nicecert", "realname",
    "captcha",
    # binary download / export endpoints — return a file, not an HTML page, so they
    # must never enter the page frontier (real attachments are handled separately by
    # discover_attachments via file extension). eGov variants: fileDown.do,
    # dwndExcel.do, downExcel.do, excelDown.do, fileDownload.do.
    "filedown", "filedownload", "dwndexcel", "downexcel", "exceldown", "exceldownload",
)

# SEGMENT tokens — short/ambiguous words matched ONLY as a full path segment
# (exact normalized stem), so 'border'≠order, 'cartoon'≠cart, 'adjoin'≠join.
_SEGMENT_TOKENS: frozenset[str] = frozenset({
    "join", "cart", "basket", "payment", "checkout",
})

_NORM_RE = re.compile(r"[^a-z0-9]")


def _norm(segment: str) -> str:
    """Lowercase and drop non-alphanumerics (so find-id→findid, pw_search→pwsearch)."""
    return _NORM_RE.sub("", segment.lower())


def is_non_content_url(url_or_path: str) -> bool:
    """True if the URL/path is an auth/account/utility page with no KB value.

    Engine rule applied by every crawler's link-discovery so login / find-id /
    pw_search / join / mypage / self-cert / cart pages never enter the frontier
    or the knowledge base — on any site, current or future.
    """
    if not url_or_path:
        return False
    path = urlparse(url_or_path).path if "://" in url_or_path else url_or_path
    norm_path = _norm(path)
    if any(tok in norm_path for tok in _STRONG_TOKENS):
        return True
    return any(
        seg and _norm(seg.split(".", 1)[0]) in _SEGMENT_TOKENS
        for seg in path.split("/")
    )


def is_landing_hub(url_or_path: str) -> bool:
    """True if the URL/path is an eGov subsystem landing hub (`/main/main.do`).

    랜딩 허브는 내용 없는 내비/대시보드 페이지지만 링크가 풍부한 BFS 진입점이다.
    frontier 차단(is_non_content_url)이 아니라 *적재(publish)* 단계에서만 제외하기
    위한 별도 규칙 — crawl·link 발견은 유지한다.
    """
    if not url_or_path:
        return False
    path = urlparse(url_or_path).path if "://" in url_or_path else url_or_path
    return path.lower().rstrip("/").endswith("/main/main.do")
