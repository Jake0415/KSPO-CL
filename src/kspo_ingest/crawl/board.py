"""Board page item extraction and freshness filtering.

Korean government sites commonly use table-based board layouts with date columns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from kspo_ingest.crawl.spa import effective_parts, is_spa_url, restore_route

_DATE_PATTERNS = [
    re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"),
    re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})"),
]

# 패밀리 사이트(경정 kboat·경륜 kcycle 등)는 상세 링크가 <a href="javascript:void(0)"
# onclick="fnMoveDetail('9426', ...)"> 형태다. onclick의 첫 숫자 인자가 글 ID이며,
# 상세 URL은 목록 경로에 그 ID를 붙인 {list_path}/{id}로 GET 가능하다.
_ONCLICK_ID_RE = re.compile(r"[A-Za-z_]\w*\(\s*['\"]?(\d+)")


@dataclass
class BoardItem:
    url: str
    posted_at: datetime
    is_notice: bool = False


def _parse_date(text: str) -> datetime | None:
    text = text.strip()
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
            except ValueError:
                continue
    return None


_NOTICE_MARKERS = ("공지", "notice")


def _is_notice_row(row) -> bool:
    cls = (row.attributes.get("class") or "").lower()
    if "notice" in cls:
        return True
    if row.css_first('.icon_notice, .badge-notice, [data-notice="true"]') is not None:
        return True
    for icon in row.css("img[alt]"):
        if (icon.attributes.get("alt") or "").strip().lower() in _NOTICE_MARKERS:
            return True
    first_cell = row.css_first("td")
    if first_cell is not None:
        txt = first_cell.text(strip=True).lower()
        if txt in ("공지", "notice"):
            return True
    return False


def _script_detail_url(html: str, base_url: str, call: str, item_id: str) -> str | None:
    """Resolve only literal read-only actions and their ID argument; never execute JS."""
    fn = re.search(r"([A-Za-z_]\w*)\(\s*['\"]?\d+", call)
    if not fn:
        return None
    script = re.sub(r"/\*[\s\S]*?\*/", "", html)
    definition = re.search(
        r"function\s+" + re.escape(fn[1]) + r"\s*\(\s*(\w+)[^)]*\)\s*\{([^}]{0,5000})\}", script
    )
    if not definition:
        return None
    argument, body = definition.groups()
    route = re.search(r"['\"](/[^'\"\s]+\.(?:do|kspo)(?:\?[^'\"]*)?)['\"]", body)
    if not route or not re.search(r"view|detail", route[1], re.I):
        return None
    key = re.search(r"['\"][?&](\w+)=['\"]\s*\+\s*" + re.escape(argument) + r"\b", body)
    tree = HTMLParser(html)
    if key:
        param = key[1]
    else:
        field = re.search(
            r"\$\(['\"]#([\w-]+)['\"]\)\.val\(\s*" + re.escape(argument) + r"\s*\)", body
        )
        if not field:
            return None
        node = tree.css_first('[id="' + field[1] + '"]')
        param = (node.attributes.get("name") if node else None) or field[1]
    target = urlsplit(urljoin(base_url, route[1]))
    if target.hostname != urlsplit(base_url).hostname:
        return None
    query = [(k, v) for k, v in parse_qsl(target.query) if k != param]
    # Retain static board identity, not user search criteria or empty values.
    for node in tree.css('input[type="hidden"][name]'):
        name = node.attributes.get("name") or ""
        value = node.attributes.get("value") or ""
        if name in {"board_id", "boardId", "boardSeq", "board_seq", "bbsId", "menuNo"} and value:
            query.append((name, value))
    query.append((param, item_id))
    return f"{target.scheme}://{target.netloc}{target.path}?{urlencode(dict(query))}"


def _onclick_detail_url(base_url: str, item_id: str) -> str | None:
    """onclick 기반 링크의 상세 URL 생성.

    두 가지 상세 URL 방식을 지원한다:
    - 파라미터형(eGov boardList.do): 링크가 fnBoardContentView('id') onclick인 사이트
      (spoinfo·sports.re.kr·css). 목록 URL의 boardList.do를 boardView.do로 바꾸고
      콘텐츠 ID 파라미터를 부착한다. ID 파라미터명은 쿼리 스타일로 추정:
      snake_case(board_seq=…) → con_seq, camelCase(boardSeq=…) → conSeq.
    - 경로형: 그 외(패밀리 kboat·kcycle 등 fnMoveDetail). 목록 경로에 /{id} 부착.
    """
    parts = urlsplit(base_url)
    path = parts.path
    if path.endswith("boardList.do"):
        view_path = path[: -len("boardList.do")] + "boardView.do"
        # 목록 페이지 번호(pageNo 등)는 글 정체성이 아니므로 상세 URL에서 제거한다.
        # (제거 안 하면 같은 글이 목록 페이지별로 다른 소스가 돼 SONAR에서 중복된다.)
        qs = [
            (k, v)
            for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
            if k not in _KNOWN_PAGE_PARAMS
        ]
        id_param = "con_seq" if any("_" in k for k, _ in qs) else "conSeq"
        qs.append((id_param, item_id))
        return f"{parts.scheme}://{parts.netloc}{view_path}?{urlencode(qs)}"
    # KSPO 표준 eGov: <path>/list.do?… → <path>/view.do?nttId=id
    # (svoucher·dvoucher 등 goView('id') 목록. else 경로형은 list.do/{id} 404를 만든다.)
    if path.endswith("/list.do"):
        view_path = path[: -len("/list.do")] + "/view.do"
        return f"{parts.scheme}://{parts.netloc}{view_path}?nttId={item_id}"
    # 경로형 목록(soma goDetail): <base>/<cat?>/list → <base>/{id}
    # 말단 'list'와 그 앞 숫자 카테고리 세그먼트(/03 등)를 제거하고 /{id} 부착.
    segs = [s for s in path.split("/") if s]
    if segs and segs[-1] == "list":
        segs = segs[:-1]
        if segs and segs[-1].isdigit():
            segs = segs[:-1]
        return f"{parts.scheme}://{parts.netloc}/" + "/".join([*segs, item_id])
    # Unknown action endpoints need explicit navigation evidence, not invented paths.
    if path.lower().endswith((".do", ".kspo")):
        return None
    # 그 외(kboat·kcycle fnMoveDetail): 목록 경로에 /{id} 부착.
    return f"{base_url.split('?', 1)[0].rstrip('/')}/{item_id}"


def extract_board_items(html: str, *, base_url: str) -> list[BoardItem]:
    if not html:
        return []
    tree = HTMLParser(html)
    items: list[BoardItem] = []
    seen: set[str] = set()
    rows = tree.css("tr")
    if not any(r.css_first("a[href]") or r.css_first("a[onclick]") for r in rows):
        # 표 기반이 아닌(카드/리스트형) eGov 게시판은 tr이 없다. li/div 컨테이너로 폴백.
        rows = tree.css("li, div.item, div.list-item, article")
    for row in rows:
        link_node = row.css_first("a[href]") or row.css_first("a[onclick]")
        if link_node is None:
            continue
        href = (link_node.attributes.get("href") or "").strip()
        if href and (is_spa_url(href) or not href.startswith(("#", "javascript:"))):
            absolute = urljoin(base_url, href)
        else:
            # JS 링크: ID가 onclick 속성 또는 href="javascript:fnXxx('id')" 어느 쪽에도 올 수 있다.
            # kboat: fnMoveDetail / sports·spoinfo: fnBoardContentView.
            js = f"{link_node.attributes.get('onclick') or ''} {href}"
            m = _ONCLICK_ID_RE.search(js)
            if not m:
                continue
            absolute = _script_detail_url(html, base_url, js, m.group(1)) or _onclick_detail_url(
                base_url, m.group(1)
            )
            if absolute is None:
                continue
            if urlsplit(base_url).hostname == "soma.kspo.or.kr":
                soma = re.search(r"goDetail\(['\"](\d+)['\"]\s*,\s*['\"]([A-Za-z0-9]+)['\"]", js)
                if soma and urlsplit(base_url).path.startswith("/customer/notice/"):
                    absolute = urljoin(base_url, f"/customer/notice/{soma[1]}/{soma[2]}")
        row_text = row.text(separator=" ")
        field = row.css_first('time, [class*="date"], .posted, .regdate')
        date_text = (
            (field.attributes.get("datetime") or field.text(separator=" ")) if field else row_text
        )
        posted_at = _parse_date(date_text)
        if posted_at is None:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        items.append(BoardItem(url=absolute, posted_at=posted_at, is_notice=_is_notice_row(row)))
    return items


def is_within_freshness(
    posted_at: datetime,
    *,
    freshness_days: int = 90,
    now: datetime | None = None,
) -> bool:
    if now is None:
        now = datetime.now(UTC)
    cutoff = now - timedelta(days=freshness_days)
    return posted_at >= cutoff


def is_old_board_page(
    items: list[BoardItem], *, freshness_days: int = 90, now: datetime | None = None
) -> bool:
    """Pinned notices do not determine the chronological pagination boundary."""
    ordinary = [item for item in items if not item.is_notice]
    return bool(ordinary) and all(
        not is_within_freshness(item.posted_at, freshness_days=freshness_days, now=now)
        for item in ordinary
    )


def classify_freshness(
    posted_at: datetime | None,
    *,
    freshness_days: int = 90,
    now: datetime | None = None,
) -> str:
    """freshness 3분기 판정 — 게이트/크론 공용."""
    if posted_at is None:
        return "no_date"
    return (
        "ok" if is_within_freshness(posted_at, freshness_days=freshness_days, now=now) else "stale"
    )


@dataclass
class BoardSignal:
    is_board: bool
    score: int
    has_pagination: bool
    has_goview: bool
    dated_rows: int


_PAGE_SIG_RE = re.compile(r"(?:pageNo|pageIndex|page)=\d+")
# 상세 이동 JS 호출 시그널. 인자의 따옴표가 &quot; 등으로 인코딩된 raw HTML에서도
# 걸리도록 함수 호출부(이름+괄호)까지만 매칭한다.
_GOVIEW_SIG_RE = re.compile(r"(?:goView|fn\w*View|fnMoveDetail|fn\w*Detail)\s*\(")
# 링크 기반 상세 이동(카드/리스트형 eGov 게시판): view.do/boardView.do 또는 /{id}? 형태.
_VIEW_HREF_RE = re.compile(r"(?:view\.do|boardView\.do)\b|/\d+\?")


def classify_board_list(html: str, *, base_url: str) -> BoardSignal:
    """Verify a single dated list in the content body, not global navigation."""
    from kspo_ingest.crawl.board_validation import validate_board

    result = validate_board(html, base_url, urlsplit(base_url).hostname or "")
    return BoardSignal(
        result.valid,
        3 if result.valid else 0,
        bool(_PAGE_SIG_RE.search(html)),
        result.valid,
        result.item_count,
    )


# 사이트별 페이지네이션 파라미터. 도메인마다 다르다:
#   KSPO eGov(.do): pageIndex / 일부 pageNo·page
#   패밀리 kboat·kcycle(Thymeleaf): pagination.currentPage
#   ksponco(esafer): nPage / sports.re.kr 입찰: num_p
# domain.board_page_param으로 도메인별 지정하는 게 가장 확실하고, 미지정 시 URL에서 감지한다.
_KNOWN_PAGE_PARAMS = (
    "pagination.currentPage",
    "nPage",
    "pageIndex",
    "pageNo",
    "num_p",
    "page",
)

# 사이트별 페이지네이션 파라미터(호스트 기준). 목록 URL에 파라미터가 없어 자동감지가
# 불가능한 사이트(kboat/kcycle는 무-파라미터 경로, ksponco는 esafer)에서 필요하다.
# DB 컬럼 대신 호스트 맵으로 관리(모델 스키마 변경 불필요).
_HOST_PAGE_PARAM: dict[str, str] = {
    "soma.kspo.or.kr": "form_page_index",
    "www.kboat.or.kr": "pagination.currentPage",
    "www.kcycle.or.kr": "pagination.currentPage",
    "www.ksponco.or.kr": "nPage",
    "ksponco.or.kr": "nPage",
    "www.sports.re.kr": "pageNo",
    "www.spoinfo.or.kr": "pageNo",
}


def page_param_for_host(host: str | None) -> str | None:
    """호스트에 지정된 페이지네이션 파라미터(없으면 None → build_page_url이 자동감지)."""
    return _HOST_PAGE_PARAM.get((host or "").lower())


def build_page_url(list_url: str, page_no: int, *, param: str | None = None) -> str:
    """list_url의 페이지 파라미터를 page_no로 치환/부착.

    param override(도메인 설정) > URL에서 기존 파라미터 감지 > 기본 'pageIndex'.
    param에 점(pagination.currentPage) 등이 있어도 안전하도록 re.escape 사용.
    """
    if is_spa_url(list_url):
        parts = effective_parts(list_url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        values = dict(pairs)
        # SPA cursors belong inside the fragment, never on the document URL.
        if "offset" in values or "max" in values:
            size = values.get("max", "20")
            if not size.isdigit() or int(size) <= 0:
                return list_url
            cursor, value = "offset", str((page_no - 1) * int(size))
        else:
            cursor = next((k for k, _ in pairs if k in _KNOWN_PAGE_PARAMS), None)
            if cursor is None:
                return list_url  # No evidence: do not invent a pagination route.
            value = str(page_no)
        pairs = [(k, v) for k, v in pairs if k != cursor] + [(cursor, value)]
        return restore_route(list_url, urlunsplit(parts._replace(query=urlencode(pairs))))
    if param is None:
        for p in _KNOWN_PAGE_PARAMS:
            if re.search(rf"[?&]{re.escape(p)}=\d+", list_url):
                param = p
                break
        else:
            param = "pageIndex"
    if urlparse(list_url).hostname == "soma.kspo.or.kr" and "_form_id=" not in list_url:
        list_url += ("&" if "?" in list_url else "?") + "_form_id=form"
    stripped = re.sub(rf"[&?]{re.escape(param)}=\d+", "", list_url)
    sep = "&" if "?" in stripped else "?"
    return f"{stripped}{sep}{param}={page_no}"


def canonical_board_list_url(url: str) -> str | None:
    """임의의 게시판 관련 URL을 '정식 목록 URL'로 정규화한다.

    게시판의 정체성은 목록 페이지다. 따라서 게시글(view.do) URL이면 목록(list.do)으로
    역산하고, 게시판 식별자인 menuNo만 남기고 pageIndex/searchWrd 등 가변 파라미터는
    버린다. 같은 게시판의 http/https·bare-dir·view·list 변형이 하나의 키로 수렴하므로
    board_source의 UNIQUE(domain_id, list_url) 제약이 중복을 자동으로 흡수한다.

    탐지(board_detect)와 등록(auto_register)이 공유하는 단일 규칙이며,
    이 규칙을 벗어난 URL은 게시판으로 등록하지 않는다.

    - KSPO .do 게시판: <path>/{view,list}.do?...menuNo=N... → <path>/list.do?menuNo=N
    - menuNo 없는 .do 또는 게시글: 게시판 식별 불가 → None
    - 비-.do(경로 기반 패밀리 사이트): 여기서 판별하지 않음 → None (호출부에서 별도 처리)
    """
    path = url.split("?", 1)[0]
    if not (path.endswith("/view.do") or path.endswith("/list.do")):
        return None
    m = re.search(r"menuNo=(\d+)", url)
    if not m:
        return None
    base = re.sub(r"/(?:view|list)\.do$", "/list.do", path)
    return f"{base}?menuNo={m.group(1)}"


def empty_board_reason(html: str, *, base_url: str) -> str:
    """Distinguish a real unparsed article from navigation on an empty list.

    Only use DOM evidence; images are not downloaded or OCR-processed.
    """
    from kspo_ingest.crawl.board_identity import is_detail_url

    tree = HTMLParser(html)
    tree.strip_tags(["script", "style", "noscript", "template", "header", "footer", "nav", "aside"])
    scope = tree.css_first('main, [role="main"], #content, #contents, #container') or tree.body
    if scope is None:
        return "empty_list"
    base_path = effective_parts(base_url).path.rstrip("/")
    for link in scope.css("a[href], a[onclick]"):
        parent = link
        navigation = False
        while parent is not None and parent is not scope:
            classes = (parent.attributes.get("class") or "").lower().split()
            if any(re.search(r"pag(?:e|ing|ination)|(?:^|-)menu$", name) for name in classes):
                navigation = True
                break
            parent = parent.parent
        if navigation:
            continue
        href = (link.attributes.get("href") or "").strip()
        if href and (
            is_spa_url(href) or not href.lower().startswith(("#", "javascript:", "mailto:", "tel:"))
        ):
            url = urljoin(base_url, href)
            path = effective_parts(url).path
            if is_detail_url(url) or re.fullmatch(re.escape(base_path) + r"/\d+/?", path):
                return "unparsed_list"
        action = (link.attributes.get("onclick") or "") + " " + href
        # Numeric IDs in unknown list actions still require review, but paging,
        # search and global controls do not prove that an article exists.
        calls = re.findall(r"([A-Za-z_]\w*)\(\s*['\"]?(\d+)", action)
        for name, _ in calls:
            if name.lower() in {"void", "alert", "confirm"}:
                continue
            if not re.search(
                r"search|paging|pagination|page|sort|filter|menu|toggle|print|share", name, re.I
            ):
                return "unparsed_list"
    return "empty_list"


def next_spa_page_url(html: str, current_url: str, page_no: int) -> str | None:
    """Prefer an actual next cursor link; use observed offset/page query as fallback."""
    from kspo_ingest.crawl.board_identity import CURSORS, board_key

    current = effective_parts(current_url)
    values = dict(parse_qsl(current.query))
    family = board_key(current_url)
    choices = []
    for anchor in HTMLParser(html).css("a[href]"):
        href = anchor.attributes.get("href") or ""
        if not is_spa_url(href):
            continue
        target = urljoin(current_url, href)
        if board_key(target) != family:
            continue
        query = dict(parse_qsl(effective_parts(target).query))
        for key, value in query.items():
            before = values.get(key, "0")
            if (
                key.lower() in CURSORS
                and value.isdigit()
                and before.isdigit()
                and int(value) > int(before)
            ):
                choices.append((int(value), target))
    if choices:
        return min(choices)[1]
    fallback = build_page_url(current_url, page_no + 1)
    return fallback if fallback != current_url else None


def next_board_page_url(
    html: str, current_url: str, page_no: int, *, param: str | None = None
) -> str | None:
    """Use actual paging controls before synthesizing an unseen page number."""
    if is_spa_url(current_url):
        return next_spa_page_url(html, current_url, page_no)
    from kspo_ingest.crawl.board_identity import board_key, is_detail_url

    def paging_family(url):
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in {"b_list_cnt"} and v]
        return board_key(urlunsplit(parts._replace(query=urlencode(query))))

    current = urlsplit(current_url)
    family = paging_family(current_url)
    choices = []
    has_paging = False
    for node in HTMLParser(html).css("a[href], a[onclick]"):
        href = (node.attributes.get("href") or "").strip()
        action = href + " " + (node.attributes.get("onclick") or "")
        match = re.search(r"(?:goPage|fnPage|fnPaging)\(\s*['\"]?(\d+)", action, re.I)
        if match:
            has_paging = True
            number = int(match[1])
            if number > page_no:
                choices.append((number, build_page_url(current_url, number, param=param)))
            continue
        if not href or href.startswith(("#", "javascript:")):
            continue
        target = urljoin(current_url, href)
        parsed = urlsplit(target)
        if (parsed.netloc, parsed.path) != (current.netloc, current.path):
            continue
        if is_detail_url(target) or family is None or paging_family(target) != family:
            continue
        for key, value in parse_qsl(parsed.query):
            if key in _KNOWN_PAGE_PARAMS and value.isdigit():
                has_paging = True
                if int(value) > page_no:
                    choices.append((int(value), target))
    if choices:
        return min(choices)[1]
    if has_paging:
        return None
    return build_page_url(current_url, page_no + 1, param=param)
