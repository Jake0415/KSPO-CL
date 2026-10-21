"""내부 링크 추출 — 같은 호스트 페이지 URL을 발견하여 BFS frontier 입력으로 활용.

`discover_attachments`가 첨부(.pdf 등)만 처리하는 것과 달리, 본 모듈은 같은 host로
이어지는 일반 페이지 URL을 추출한다. 결과는 호출자가 `pages` 테이블에 status=DISCOVERED
로 upsert하여 다음 incremental Job에서 처리되도록 한다.
"""

from __future__ import annotations

import os
import re
from html import unescape
from urllib.parse import parse_qsl, urljoin, urlparse

from selectolax.parser import HTMLParser

from kspo_ingest.attach.discovery import ATTACHMENT_EXTS, IGNORED_EXTS, is_attachment_url
from kspo_ingest.crawl.url_class import is_non_content_url
from kspo_ingest.crawl.url_normalize import canonical_url

# 내부 링크에서도 제외하는 확장자 (이미지/미디어/실행파일 + 첨부는 별도 경로로 처리)
_SKIP_EXTS = ATTACHMENT_EXTS | IGNORED_EXTS


def _is_skip_path(path: str) -> bool:
    """크롤 가치 없는 경로(로그인/회원/인증/유틸)인지 — 엔진 공통 규칙 위임."""
    return is_non_content_url(path)


def _dedup_key(parsed) -> str:
    """Use the same content identity as storage; keep cursor/filter query values."""
    return canonical_url(parsed.geturl())


def discover_internal_links(
    html: str, *, base_url: str, host: str, max_links: int | None = None
) -> list[str]:
    """페이지 HTML에서 같은 host 일반 페이지 URL을 절대 URL로 반환.

    필터:
    - href가 비어있거나 javascript:/mailto:/# 시작 → 제외
    - urljoin 후 host 미일치 → 제외 (외부 링크 차단)
    - .pdf/.docx/.zip 등 첨부 확장자 → 제외 (extract_links가 처리)
    - .jpg/.png/.mp4 등 이미지·미디어 → 제외
    - 로그인/회원가입/마이페이지 경로 → 제외
    - 콘텐츠 정체성 URL 중복 제거 (페이지 커서·필터는 보존)
    - max_links 초과 → 절단

    NOTE: BFS depth/frontier 진입 결정은 호출자(pipeline)가 함. 본 함수는 후보만 반환.
    """
    if not html:
        return []
    tree = HTMLParser(html)
    seen: set[str] = set()
    out: list[str] = []

    def _add(url: str) -> None:
        if max_links is not None and len(out) >= max_links:
            return
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return
        if parsed.netloc.lower() != host.lower():
            return
        _, ext = os.path.splitext(parsed.path or "")
        if ext.lower() in _SKIP_EXTS or is_attachment_url(url):
            return
        if any(
            key.lower()
            in {"contsn", "classsn", "notice_seq", "nttid", "conseq", "con_seq", "suppbusiinfoseq"}
            and not value.strip()
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ):
            return
        if _is_skip_path(parsed.path):
            return
        key = _dedup_key(parsed)
        if key in seen:
            return
        seen.add(key)
        out.append(url)

    # 1. <a href> 링크
    for node in tree.css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        _add(urljoin(base_url, unescape(href)))

    # 2. onclick goView/fnView 패턴 — 공공 게시판 상세 페이지
    # goView('63978') → list.do를 view.do?nttId=63978 로 변환
    _add_board_view_links(html, base_url, _add)

    # 3. JS/onclick 내비게이션 — 경로 문자열 리터럴을 직접 추출.
    # 메뉴가 href가 아니라 fnPageMove('/info/schedPlan.kspo') · location.href='/a/b.do'
    # 형태인 사이트(sqms 등)의 GNB/LNB/사이드/푸터 링크를 범용으로 발견한다.
    _add_js_nav_links(html, base_url, _add)

    # 4. 게시판 페이지네이션 — list 페이지에서 pageNo=2,3,... 생성
    _add_pagination_links(html, base_url, _add)

    return out


# JS/onclick 내비게이션 — 동적 페이지 확장자를 가진 내부 경로 리터럴.
# 예: fnPageMove('/info/schedPlan.kspo'), location.href="/a/b.do?x=1", goMenu("/c.jsp")
# add_fn 내부에서 host·확장자·비콘텐츠 경로 필터와 dedup을 거치므로 과추출은 안전하게 걸러진다.
_JS_PATH_RE = re.compile(
    r"""['"](/[A-Za-z0-9_\-./]+\.(?:kspo|do|jsp|php|asp|aspx|html?)(?:\?[^'"]*)?)['"]"""
)


def _add_js_nav_links(html: str, base_url: str, add_fn) -> None:
    """onclick/JS 문자열에서 내부 페이지 경로를 추출해 링크 후보로 추가."""
    for m in _JS_PATH_RE.finditer(html):
        # A JS URL template immediately followed by a dynamic ID is not a page URL.
        following = html[m.end() : m.end() + 180]
        if re.search(r"(?:view|detail)\.(?:do|kspo)$", m.group(1), re.I) and re.search(
            r"['\"]\?\w+=['\"]\s*\+", following
        ):
            continue
        add_fn(urljoin(base_url, unescape(m.group(1))))


# 공공 게시판 onclick 패턴 → view URL 생성
_GO_VIEW_RE = re.compile(r"""(?:goView|fn\w*View)\(\s*['"](\d+)['"]\s*\)""")


def _add_board_view_links(html: str, base_url: str, add_fn) -> None:
    """onclick="goView('ID')" 패턴에서 게시글 view URL을 생성.

    패턴: list.do → view.do?nttId=ID
    예: /dvoucher/bbs/B0000078/list.do → /dvoucher/bbs/B0000078/view.do?nttId=63978
    """
    parsed_base = urlparse(base_url)
    base_path = parsed_base.path

    from kspo_ingest.crawl.board import _script_detail_url

    resolved = set()
    for call in re.finditer(r"[A-Za-z_]\w*\(\s*['\"](\d+)['\"]", html):
        target = _script_detail_url(html, base_url, call.group(0), call.group(1))
        if target:
            resolved.add(call.group(1))
            add_fn(target)

    # list.do → view.do 변환 가능한 경우만
    if "list.do" not in base_path and "List" not in base_path:
        return

    view_path = base_path.replace("list.do", "view.do").replace("List.do", "View.do")
    if view_path == base_path:
        # boardList.do → boardView.do 패턴
        view_path = re.sub(r"[Ll]ist\.do", "View.do", base_path)
        if view_path == base_path:
            return

    for m in _GO_VIEW_RE.finditer(html):
        ntt_id = m.group(1)
        if ntt_id in resolved:
            continue
        view_url = f"{parsed_base.scheme}://{parsed_base.netloc}{view_path}?nttId={ntt_id}"
        add_fn(view_url)


# 페이지네이션 최대 페이지 추출 패턴
_PAGE_NUM_RE = re.compile(
    r"""(?:goPage|fnPage|fn\w*Page)\(\s*['"]?(\d+)['"]?\s*(?:,\s*['"][^'"]*['"])?\s*\)"""
)
# href 페이지네이션 파라미터 — 긴 이름 우선으로 접두 오매칭 방지.
# selectolax가 파싱·엔티티 디코딩한 href 값에 적용(raw HTML의 &amp; 인코딩 회피).
_HREF_PAGE_RE = re.compile(r"(pageIndex|pageNo|page)=(\d+)")


def _add_pagination_links(html: str, base_url: str, add_fn) -> None:
    """게시판 목록 페이지에서 페이지네이션 링크 생성.

    실제 href는 그대로 사용한다. JS goPage()만 있으면 명시된 번호만
    pageNo로 변환하며, 2부터 최대 번호까지 임의로 생성하지 않는다.
    list.do, List.kspo, boardList.do 등 목록 페이지에서만 동작.
    """
    parsed = urlparse(base_url)
    path_lower = parsed.path.lower()

    # 목록 페이지인지 확인
    if not any(kw in path_lower for kw in ("list.do", "list.kspo", "boardlist", "/list")):
        return

    # href 기반 페이지네이션 — 파싱된 href 값에서 파라미터명별 최대 페이지 번호.
    # (raw 정규식은 &amp;pageIndex=16 같은 엔티티 인코딩을 놓치므로 selectolax 사용)
    param_max: dict[str, int] = {}
    tree = HTMLParser(html)
    for node in tree.css("a[href]"):
        m = _HREF_PAGE_RE.search(node.attributes.get("href") or "")
        if m:
            name, num = m.group(1), int(m.group(2))
            param_max[name] = max(param_max.get(name, 0), num)

    if param_max:
        param = max(param_max, key=lambda k: param_max[k])
        max_page = param_max[param]
    else:
        # JS goPage('N')만 있는 경우 — 파라미터명 미상, pageNo로 폴백
        js_pages = {int(m.group(1)) for m in _PAGE_NUM_RE.finditer(html)}
        if not js_pages:
            return
        param = "pageNo"
        max_page = max(js_pages)

    if max_page <= 1:
        return

    # Actual href destinations have already been collected; never synthesize their range.
    if param_max:
        return

    # JS-only pagination: use only the page numbers explicitly supplied.
    base_no_page = re.sub(rf"[&?]{param}=\d+", "", base_url)
    sep = "&" if "?" in base_no_page else "?"
    for page_num in sorted(js_pages - {1}):
        page_url = f"{base_no_page}{sep}{param}={page_num}"
        add_fn(page_url)
