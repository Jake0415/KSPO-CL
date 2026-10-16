"""Pure URL-generation / identity logic for the sports.re.kr crawler.

All rules here were validated against the live site (2026-07-06). No network,
no side effects — every function is unit-testable in isolation.

Reference: docs/superpowers/specs/2026-07-06-sports-re-kr-crawler-spec.md
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

HOST = "www.sports.re.kr"
BASE = f"https://{HOST}"

# --- JS-handler regexes on list HTML (rows hide behind javascript:fn*()) -------
RE_BOARD_VIEW = re.compile(r"fnBoardContentView\(\s*'(\d+)'\s*\)")
RE_GO_PAGE = re.compile(r"fnGoPage\(\s*'(\d+)'")
RE_VOC_VIEW = re.compile(r"fnVocView\(\s*'(VB\d+)'\s*\)")
RE_ARTCTRLNO = re.compile(r"([A-Z]{2}_\d+)")
# research/pub/bid rows: fnDetail(artctrlno,bibctrlno,libSeq) | fnDetail(num_p)
RE_FNDETAIL_ART = re.compile(r"fnDetail\(\s*'([A-Z]{2}_\d+)'")
RE_FNDETAIL_NUM = re.compile(r"fnDetail\(\s*'(\d+)'\s*\)")
RE_FILE_DOWN = re.compile(
    r"fnFileDownAction\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)"
)
RE_PYXIS = re.compile(r"/pyxis-api/1/digital-files/([0-9a-fA-F-]{36})")

# Identity params kept per unit type; everything else (menu_seq, pageNo,
# bibctrlno, lib_seq, ordering) is stripped from the canonical URL.
IDENTITY_PARAMS = {
    "board": ("board_seq", "con_seq"),
    "research": ("artctrlno",),
    "static": ("page_seq",),
    "bid": ("num_p",),
    "voc": ("voc_id",),
    "pub": ("artctrlno",),
}

BOARD_VARIANTS = ("bs", "ns", "fq", "job")


# --- URL builders -------------------------------------------------------------
def board_list_url(board_seq: int, menu_seq: int, page: int = 1,
                   variant: str = "bs", extra: dict | None = None) -> str:
    q = {"board_seq": board_seq, "menu_seq": menu_seq, "pageNo": page}
    if extra:
        q.update(extra)
    return f"{BASE}/front/board/{variant}/boardList.do?{urlencode(q)}"


def board_view_url(board_seq: int, con_seq: int, menu_seq: int | None = None,
                   variant: str = "bs") -> str:
    q = {"board_seq": board_seq, "con_seq": con_seq}
    if menu_seq is not None:
        q["menu_seq"] = menu_seq
    return f"{BASE}/front/board/{variant}/boardView.do?{urlencode(q)}"


def research_view_url(artctrlno: str, menu_seq: int = 594) -> str:
    q = {"menu_seq": menu_seq, "artctrlno": artctrlno, "bibctrlno": artctrlno}
    return f"{BASE}/front/research/project/orginView.do?{urlencode(q)}"


def pub_view_url(artctrlno: str, menu_seq: int) -> str:
    q = {"menu_seq": menu_seq, "artctrlno": artctrlno, "bibctrlno": artctrlno}
    return f"{BASE}/front/research/pub/orginView.do?{urlencode(q)}"


def bid_view_url(num_p: str, menu_seq: int) -> str:
    q = {"menu_seq": menu_seq, "num_p": num_p}
    return f"{BASE}/front/info/bid/notifyView.do?{urlencode(q)}"


def page_view_url(page_seq: int, menu_seq: int | None = None) -> str:
    q = {}
    if menu_seq is not None:
        q["menu_seq"] = menu_seq
    q["page_seq"] = page_seq
    return f"{BASE}/front/page/pageView.do?{urlencode(q)}"


def file_download_url(file_path: str, real_nm: str) -> str:
    q = {"file_path": file_path, "file_real_nm": real_nm}
    return f"{BASE}/front/file/fileDownAct.do?{urlencode(q)}"


# --- Identity / dedup ---------------------------------------------------------
def canonical_url(url: str, unit_type: str) -> str:
    """Strip navigation noise; keep only identity params for `unit_type`.

    Same content unit reached via different menu_seq / pageNo / search collapses
    to one canonical URL.
    """
    parts = urlsplit(url)
    qs = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=False).items()}
    keep = IDENTITY_PARAMS.get(unit_type, ())
    ident = {k: qs[k] for k in keep if k in qs and qs[k] != ""}
    path = parts.path
    # normalise research bibctrlno mirror away (already excluded by keep)
    new_q = urlencode(sorted(ident.items()))
    return urlunsplit((parts.scheme or "https", parts.netloc or HOST, path, new_q, ""))


def natural_id(unit_type: str, **ids) -> str:
    if unit_type == "board":
        return f"{ids['board_seq']}:{ids['con_seq']}"
    if unit_type in ("research", "pub"):
        return str(ids["artctrlno"])
    if unit_type == "static":
        return str(ids["page_seq"])
    if unit_type == "bid":
        return str(ids["num_p"])
    if unit_type == "voc":
        return str(ids["voc_id"])
    if unit_type == "media":
        return str(ids["external_url"])
    if unit_type == "faq":
        return f"faq:{ids['board_seq']}"
    raise ValueError(f"unknown unit_type {unit_type}")


def dedup_key(host: str, unit_type: str, nat_id: str) -> str:
    return f"{host}|{unit_type}|{nat_id}"


# --- Classification / guards --------------------------------------------------
def is_auth_wall(html: str, status: int = 200) -> bool:
    """Detect the NICE identity stub served for gated pages (내서재 etc.)."""
    if not html:
        return False
    low = html.lower()
    return (
        "checkplusopen.do" in low
        or "본인인증후에" in html
        or "본인확인" in html and len(html) < 600
    )


def is_js_redirect_stub(html: str) -> bool:
    """Thin JS-redirect stub (no real content)."""
    if len(html) < 800 and "window.location" in html.lower():
        return True
    return False


def unit_type_for(url: str) -> str | None:
    """Map a detail URL to its unit type (None if not a content unit)."""
    if "boardView.do" in url:
        return "board"
    if "orginView.do" in url and "/pub/" in url:
        return "pub"
    if "orginView.do" in url:
        return "research"
    if "pageView.do" in url:
        return "static"
    if "notifyView.do" in url:
        return "bid"
    if "vocView.do" in url:
        return "voc"
    return None


# --- Pagination decisions -----------------------------------------------------
@dataclass
class PageResult:
    ids: list[str]
    next_pages: list[int]


def should_stop_pagination(current_ids: list[str], prev_ids: list[str],
                           page: int, max_pages: int) -> bool:
    """Stop when: empty page, repeated id-set (CMS clamps overflow to last
    page), or safety cap exceeded."""
    if not current_ids:
        return True
    if prev_ids and current_ids == prev_ids:
        return True
    if page > max_pages:  # pages 1..max_pages inclusive
        return True
    return False


def extract_page_numbers(html: str) -> list[int]:
    """All fnGoPage('N') targets present in the pager."""
    return sorted({int(m) for m in RE_GO_PAGE.findall(html)})
