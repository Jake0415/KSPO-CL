"""One-hop external references originating from the configured source domain."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from kspo_ingest.attach.discovery import ATTACHMENT_EXTS, IGNORED_EXTS


@dataclass(frozen=True)
class ExternalLink:
    url: str
    label: str


def public_url(url: str) -> bool:
    p = urlsplit(url)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        return False
    try:
        if p.port not in (None, 80, 443):
            return False
    except ValueError:
        return False
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def discover_external_links(html: str, *, base_url: str, source_host: str) -> list[ExternalLink]:
    # External documents are terminal references, never seeds for another whole website.
    if urlsplit(base_url).hostname != source_host:
        return []
    out: dict[str, ExternalLink] = {}
    for node in HTMLParser(html).css("a[href]"):
        url = urljoin(base_url, (node.attributes.get("href") or ""))
        p = urlsplit(url)
        if not public_url(url) or p.hostname == source_host:
            continue
        path = p.path.lower()
        if any(
            part in path.split("/")
            for part in (
                "login",
                "logout",
                "signin",
                "signup",
                "share",
                "sharer",
                "sharer.php",
                "intent",
                "delete",
                "remove",
                "subscribe",
                "dialog",
            )
        ):
            continue
        if os.path.splitext(path)[1] in ATTACHMENT_EXTS | IGNORED_EXTS:
            continue
        url = urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))
        label = node.text(strip=True) or node.attributes.get("aria-label", "")
        if not label:
            image = node.css_first("img[alt]")
            label = (image.attributes.get("alt") or p.hostname) if image else p.hostname
        out.setdefault(url, ExternalLink(url, label))
    return list(out.values())


def external_metadata(html: str) -> tuple[str | None, str]:
    """Public page metadata; never treat a link itself as proof of authorship."""
    tree = HTMLParser(html)
    fields: dict[str, str] = {}
    for node in tree.css("meta[property], meta[name]"):
        key = node.attributes.get("property") or node.attributes.get("name")
        value = (node.attributes.get("content") or "").strip()
        if key and value:
            fields.setdefault(key, value)
    title = fields.get("og:title") or fields.get("twitter:title")
    lines = []
    for key, label in (
        ("og:description", "공개 설명"),
        ("twitter:description", "공개 설명"),
        ("description", "페이지 설명"),
        ("og:site_name", "플랫폼"),
        ("article:published_time", "공개 게시일"),
        ("og:image", "이미지"),
    ):
        value = fields.get(key)
        if value and value not in fields.get("_seen", ""):
            lines.append(label + ": " + value)
            fields["_seen"] = fields.get("_seen", "") + "\n" + value
    return title, "\n".join(lines)


def external_access_blocked(html: str) -> bool:
    """Do not index a sign-in/challenge wall as a social post."""
    tree = HTMLParser(html)
    text = tree.text(separator=" ", strip=True).lower()
    description = " ".join((n.attributes.get("content") or "") for n in tree.css("meta"))
    text += " " + description.lower()
    return tree.css_first('input[type="password"]') is not None or any(
        phrase in text
        for phrase in (
            "log into facebook",
            "log in to facebook",
            "log in to instagram",
            "sign in to continue",
            "로그인 후 이용",
            "로그인 후 확인",
            "verify you are human",
            "checking your browser",
            "access denied",
        )
    )
