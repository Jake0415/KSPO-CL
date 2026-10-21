"""Per-job list identity: preserve filters, ignore only navigation cursors."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlsplit

from kspo_ingest.crawl.board_identity import board_key, is_detail_url
from kspo_ingest.crawl.url_normalize import canonical_url


def list_family(url: str) -> str | None:
    if is_detail_url(url):
        return None
    return board_key(url)


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
                is_detail_url(u)
                or re.search(r"/(?:display|colect|product|notice|class)/\d+", urlsplit(u).path)
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
