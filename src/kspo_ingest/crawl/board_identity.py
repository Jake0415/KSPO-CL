"""Shared board URL semantics; unknown routes remain ordinary crawl targets."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlunsplit

from kspo_ingest.crawl.spa import effective_parts, is_spa_url, restore_route

CURSORS = {
    "page",
    "pageno",
    "pageindex",
    "form_page_index",
    "lastkey",
    "offset",
    "cursor",
    "pagination.currentpage",
    "npage",
    "num_p",
    "_form_id",
    "dummy",
    "form_page_list_count",
    "form_pc_page_count",
}
ARTICLE_IDS = {"nttid", "conseq", "con_seq", "articleid", "article_id", "list_no"}
BOARD_IDS = {"bbsid", "boardid", "boardseq", "board_seq", "bid"}


def query_pairs(query: str) -> list[tuple[str, str]]:
    return [(re.sub(r"^(?:amp;)+", "", k), v) for k, v in parse_qsl(query, keep_blank_values=True)]


def is_detail_url(url: str) -> bool:
    p = effective_parts(url)
    qs = query_pairs(p.query)
    spa_article = is_spa_url(url) and bool(
        re.search(r"/(?:notice|news|article|post)/[0-9]+/?$", p.path, re.I)
    )
    return (
        spa_article
        or any(k.lower() in ARTICLE_IDS and v for k, v in qs)
        or any(
            k.lower() in {"act", "mode", "action"} and v.lower() in {"view", "detail", "read"}
            for k, v in qs
        )
        or bool(
            re.search(r"(?:view|detail|read)\.(?:do|kspo)$|/(?:view|detail|read)/", p.path, re.I)
        )
    )


def board_key(url: str) -> str | None:
    p = effective_parts(url)
    path = re.sub(r"/page/\d+/?$", "", p.path, flags=re.I)
    qs = query_pairs(p.query)
    routed = path.lower().endswith(("/board.es", "/gallery.es"))
    detail = is_detail_url(url)
    spa_list = is_spa_url(url) and bool(
        re.search(r"/(?:notice|board|bbs|news|list)/?$", path, re.I)
    )
    if not (spa_list or routed or re.search(r"list(?:\.(?:do|kspo)|/|$)", path, re.I) or detail):
        return None
    if is_spa_url(url) and detail:
        path = re.sub(r"(/(?:notice|news|article|post))/[0-9]+/?$", r"\1", path, flags=re.I)
    if detail and not routed:
        path = re.sub(
            r"(?:view|detail|read)(?=\.(?:do|kspo)$)",
            lambda m: "List" if m[0][0].isupper() else "list",
            path,
            flags=re.I,
        )
    has_board_id = any(k.lower() in BOARD_IDS and v for k, v in qs)
    ignore = CURSORS | ARTICLE_IDS | {"act", "mode", "action"}
    if is_spa_url(url):
        ignore |= {"max"}
    if has_board_id:
        ignore |= {"topmenuseq", "menuno"}
    identity = sorted((k, v) for k, v in qs if k.lower() not in ignore)
    return restore_route(url, urlunsplit(("", p.netloc.lower(), path, urlencode(identity), "")))


def is_board_owned_link(url: str, *, confirmed_list_urls: set[str]) -> bool:
    key = board_key(url)
    return key is not None and any(key == board_key(entry) for entry in confirmed_list_urls)
