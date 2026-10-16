"""Shared, conservative board-list validation and first-entry URL identity."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from kspo_ingest.crawl.loop_guard import CURSORS
from kspo_ingest.crawl.url_normalize import TRACKING_PARAMS, normalize_url

ARTICLE_IDS = {"nttid", "conseq", "con_seq", "articleid", "article_id", "seq", "idx"}
NOISE = CURSORS | {"searchwrd", "searchcnd", "searchkey", "keyword", "sch", "searchword"}
DETAIL = re.compile(r"(?:/(?:view|detail|read)(?:[/.]|$)|boardview|/\d+/?$)", re.I)
EXCLUDED = (
    "header, footer, nav, aside, script, style, #header, #footer, .gnb, .lnb, .sidebar, "
    ".related, .related-posts, [class*=related], [class*=recommend], "
    ".recommend, .recommended, .recommendations, [data-rag-dynamic], [data-rag-links]"
)
PUBLICATION = re.compile(r"게시일|등록일|작성일|게시날짜|published|posted|등록날짜", re.I)
EVENT = re.compile(r"(?:전시|행사|교육|개최|운영|접수)\s*기간|제작\s*(?:연도|년도)")


@dataclass(frozen=True)
class BoardValidation:
    valid: bool
    entry_url: str | None
    reason: str
    item_count: int = 0


def is_landing_url(url: str) -> bool:
    """Dated preview widgets do not turn a site's landing page into a board.

    Query-routed boards may legitimately live at / or index.php, so preserve
    explicit board identity or a board/list route in the query string.
    """
    p = urlsplit(url)
    query = {k.lower(): v.lower() for k, v in parse_qsl(p.query)}
    if any(query.get(k) for k in ("bbsid", "boardid", "boardseq", "board_seq")):
        return False
    if any(
        re.search(r"(?:^|[/_.-])(?:board|bbs|list)(?:$|[/_.-])", query.get(k, ""))
        for k in ("page", "route", "module", "controller")
    ):
        return False
    leaf = p.path.rstrip("/").rsplit("/", 1)[-1].lower()
    return not leaf or bool(re.fullmatch(r"(?:main|index|home|default)(?:\.[a-z0-9]+)?", leaf))


def entry_url(url: str, host: str) -> str | None:
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or p.hostname != host or p.username or p.password:
        return None
    if is_landing_url(url):
        return None
    if re.search(
        r"/(?:login|logout|delete|insert|update|save|submit|reserve|apply)(?:[/.]|$)", p.path, re.I
    ):
        return None
    if any(
        k.lower() in {"mode", "action"}
        and v.lower() in {"view", "detail", "read", "delete", "insert", "update", "save"}
        for k, v in parse_qsl(p.query)
    ):
        return None
    path = re.sub(r"/page/\d+/?$", "", p.path, flags=re.I)
    # A view.do may identify a list, but that list must be fetched and validated separately.
    if re.search(r"(?:/view\.do|boardView\.do)$", path, re.I):
        path = re.sub(
            r"view\.do$", lambda m: "List.do" if m[0][0].isupper() else "list.do", path, flags=re.I
        )
        if not any(
            k.lower() in {"menuno", "bbsid", "boardid", "boardseq", "board_seq"}
            for k, _ in parse_qsl(p.query)
        ):
            return None
    elif DETAIL.search(path) or any(k.lower() in ARTICLE_IDS for k, _ in parse_qsl(p.query)):
        return None
    path = re.sub(r"/page/\d+/?$", "", path, flags=re.I)
    qs = sorted(
        (k, v)
        for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in NOISE | ARTICLE_IDS and k not in TRACKING_PARAMS
    )
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(qs), ""))


def validate_board(html: str, url: str, host: str) -> BoardValidation:
    from kspo_ingest.crawl.board import extract_board_items

    if is_landing_url(url):
        return BoardValidation(False, None, "landing_page_not_board")
    entry = entry_url(url, host)
    if entry is None:
        return BoardValidation(False, None, "not_list_url_or_wrong_host")
    if DETAIL.search(urlsplit(url).path) or any(
        k.lower() in ARTICLE_IDS for k, _ in parse_qsl(urlsplit(url).query)
    ):
        return BoardValidation(False, entry, "detail_requires_list_verification")
    if host == "soma.kspo.or.kr" and not urlsplit(url).path.startswith(
        ("/customer/notice", "/draw/notice")
    ):
        return BoardValidation(False, entry, "non_bulletin_content")
    tree = HTMLParser(html)
    for node in tree.css(EXCLUDED):
        node.decompose()
    root = tree.css_first("main") or tree.css_first('[role="main"]') or tree.body or tree.root
    if root is None:
        return BoardValidation(False, entry, "empty_body")
    groups = root.css("table, ul, ol, .board-list, .board_list, .bbs-list, [role='list']")
    for group in groups:
        text = group.text(separator=" ")
        if EVENT.search(text) and not PUBLICATION.search(text):
            continue
        # News/recommendation widgets without any publication evidence are not boards.
        evidence = group.css_first('time, [class*="date"], .posted, .regdate, .reg-date')
        if not PUBLICATION.search(text) and evidence is None:
            continue
        items = extract_board_items(group.html, base_url=url)
        hashes = {
            normalize_url(it.url)[1]
            for it in items
            if urlsplit(it.url).hostname == host
            and normalize_url(it.url)[1] != normalize_url(url)[1]
        }
        if len(hashes) >= 2:
            return BoardValidation(True, entry, "verified_list", len(hashes))
    return BoardValidation(False, entry, "no_dated_unique_list_in_body")
