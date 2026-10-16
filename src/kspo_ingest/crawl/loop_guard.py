"""Per-job list identity: preserve filters, ignore only navigation cursors."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from kspo_ingest.crawl.url_normalize import canonical_url

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


def list_family(url: str) -> str | None:
    p = urlsplit(url)
    if not re.search(r"(?:/list(?:\.|/|$)|boardlist|list\.(?:do|kspo))", p.path, re.I):
        return None
    qs = sorted(
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in CURSORS
    )
    return urlunsplit(("", p.netloc.lower(), p.path, urlencode(qs), ""))


def list_signature(source: str, urls: list[str]) -> str | None:
    family = list_family(source)
    if family is None:
        return None
    # Detail paths and stable article IDs only; menus must not identify a list.
    details = sorted(
        {
            canonical_url(u)
            for u in urls
            if list_family(u) is None
            and (
                re.search(r"/(?:display|colect|product|notice|class)/\d+", urlsplit(u).path)
                or re.search(r"(?:view|detail)", urlsplit(u).path, re.I)
                or (
                    urlsplit(u).path.rsplit("/", 1)[0] == urlsplit(source).path.rsplit("/", 1)[0]
                    and urlsplit(u).path.rsplit("/", 1)[-1].isdigit()
                )
                or any(
                    k.lower() in {"nttid", "conseq", "con_seq", "articleid"}
                    for k, _ in parse_qsl(urlsplit(u).query)
                )
            )
        }
    )
    if not details:
        return None
    return hashlib.sha256((family + "\n" + "\n".join(details)).encode()).hexdigest()
