from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

from selectolax.parser import HTMLParser

from kspo_ingest.attach.mime import mime_for_ext

# v2.0 Lite: 메타데이터만 저장 — 다운로드/추출/임베딩 없음.
# 모든 알려진 첨부 확장자는 동일하게 메타 기록. 무시 대상은 제외.
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"})
ATTACHMENT_EXTS: frozenset[str] = IMAGE_EXTS | frozenset(
    {".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".hwp", ".hwpx", ".zip"}
)
IGNORED_EXTS: frozenset[str] = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".mp4",
        ".mp3",
        ".avi",
        ".mov",
        ".exe",
    }
)


@dataclass(frozen=True)
class DiscoveredAttachment:
    source_url: str  # 절대 URL (urljoin 결과)
    file_name: str  # URL/링크 텍스트로 추정한 파일명
    ext: str  # ".pdf" 등 (소문자)
    mime_type: str  # 확장자 기반 추정


def _ext_from_url(url: str) -> str | None:
    """URL의 path 또는 query에서 확장자 추출. 소문자로 정규화."""
    parsed = urlparse(url)
    path = unquote(parsed.path or "")
    _, dot_ext = os.path.splitext(path)

    # KSPO 게시판: ?file_name=... 또는 ?fileName=... 패턴
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("file_name", "fileName", "filename", "fname"):
        if key in qs and qs[key]:
            _, q_ext = os.path.splitext(qs[key][0])
            if q_ext:
                return q_ext.lower()
    return dot_ext.lower() if dot_ext else None


def is_image_handler_url(url: str) -> bool:
    """Image response handlers, not HTML image gallery/detail pages.

    Match complete route basenames; noImgNm is only a fallback filename and
    must not determine the type of the actual attachment.
    """
    path = unquote(urlparse(url).path)
    return bool(re.search(r"/(?:getImage|imageDownload|imageDown)\.(?:do|kspo)$", path, re.I))


def is_attachment_url(url: str) -> bool:
    """Identify files even when served by .down/.do/.kspo handlers."""
    path = urlparse(url).path
    return (
        is_image_handler_url(url)
        or _ext_from_url(url) in ATTACHMENT_EXTS
        or bool(
            re.fullmatch(r"/pyxis-api/\d+/digital-files/[^/]+/?", path, re.I)
            or path.lower().endswith(".down")
            or re.search(r"(?:download|filedown|templatedown)(?:\.(?:do|kspo))?$", path, re.I)
        )
    )


def is_binary_content(raw: bytes, content_type: str | None) -> bool:
    """Binary attachments are metadata-only, never HTML extraction input."""
    head = raw.lstrip()[:16]
    if head.startswith((b"%PDF-", b"PK\x03\x04", b"\x89PNG", b"GIF8", b"\xff\xd8\xff")):
        return True
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return mime.startswith(("image/", "audio/", "video/")) or (
        mime.startswith(
            (
                "application/pdf",
                "application/zip",
                "application/x-msdownload",
                "application/msword",
                "application/vnd.",
            )
        )
        or (mime == "application/octet-stream" and not head.startswith(b"<"))
    )


def _file_name_from(url: str, link_text: str) -> str:
    """파일명 추정 우선순위: URL query(file_name=) → URL path basename → 링크 텍스트."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("file_name", "fileName", "filename", "fname"):
        if key in qs and qs[key]:
            return unquote(qs[key][0]).strip()

    path_basename = os.path.basename(unquote(parsed.path or ""))
    if path_basename and "." in path_basename:
        return path_basename

    text = (link_text or "").strip()
    if text:
        return text

    return path_basename or url


def url_hash_sha256(url: str) -> str:
    """source_url 기반 결정론적 hash (DB UNIQUE(domain_id, file_hash) 충족)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def discover_attachments(html: str, *, base_url: str) -> list[DiscoveredAttachment]:
    """페이지 HTML에서 첨부 후보 링크를 추출.

    1) <a href> 전수 수집
    2) urljoin(base_url, href) → 절대 URL
    3) 확장자 검사 — ATTACHMENT_EXTS만 채택, IGNORED_EXTS 제외, 그 외 무시
    4) 동일 URL 중복 제거 (같은 페이지에 같은 첨부 링크가 여러 번 등장하는 패턴)

    NOTE: 다운로드/추출/임베딩은 본 모듈 책임이 아님 (v2.0 Lite 정책).
    """
    if not html:
        return []
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[DiscoveredAttachment] = []
    for node in tree.css("a[href], a[onclick]"):
        href = (node.attributes.get("href") or "").strip()
        js = (node.attributes.get("onclick") or "") + " " + href
        match = re.search(
            r"fn_fileDownLoad\(\s*[\"\']([^\"\']+)[\"\']\s*,\s*[\"\']([^\"\']+)[\"\']", js
        )
        if match and urlparse(base_url).hostname == "soma.kspo.or.kr":
            href = "/comm/file/down?" + urlencode(
                {"fileUrl": match.group(1), "fileName": match.group(2)}
            )
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        ext = _ext_from_url(absolute)
        if ext is None or ext not in ATTACHMENT_EXTS:
            if not is_attachment_url(absolute):
                continue
            ext = ".bin"
        if ext in IGNORED_EXTS and ext not in IMAGE_EXTS:
            continue
        if ext not in ATTACHMENT_EXTS and ext != ".bin":
            continue
        if absolute in seen:
            continue
        seen.add(absolute)

        link_text = node.text(deep=True, strip=True) if hasattr(node, "text") else ""
        out.append(
            DiscoveredAttachment(
                source_url=absolute,
                file_name=_file_name_from(absolute, link_text),
                ext=ext,
                mime_type="image/*" if is_image_handler_url(absolute) else mime_for_ext(ext),
            )
        )
    # Inline body images: metadata only. Exclude global navigation and decorative chrome.
    for node in tree.css(
        "main img[src], article img[src], .board_view img[src], "
        ".board-view img[src], .view_cont img[src], .view-content img[src]"
    ):
        if any(parent.tag in {"header", "nav", "footer"} for parent in _ancestors(node)):
            continue
        absolute = urljoin(base_url, node.attributes.get("src", ""))
        ext = _ext_from_url(absolute)
        if urlparse(absolute).scheme not in {"http", "https"}:
            continue
        image_handler = is_image_handler_url(absolute)
        if ext not in IMAGE_EXTS and not image_handler:
            continue
        if image_handler:
            ext = ".bin"
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append(
            DiscoveredAttachment(
                absolute,
                _file_name_from(absolute, node.attributes.get("alt", "")),
                ext,
                "image/*" if image_handler else mime_for_ext(ext),
            )
        )
    return out


def _ancestors(node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent
