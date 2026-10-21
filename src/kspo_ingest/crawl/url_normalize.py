from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

from kspo_ingest.crawl.board_identity import ARTICLE_IDS, BOARD_IDS, CURSORS, query_pairs

# 트래킹·분석 파라미터 — 정규화 시 제거
TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "fbclid",
        "gclid",
        "_ga",
        "_gl",
        "mc_cid",
        "mc_eid",
    }
)

# KSPO 게시판 식별 파라미터 — 항상 보존
PRESERVE_PARAMS: frozenset[str] = frozenset({"bbsId", "nttId", "page", "mode", "searchKey"})

# 콘텐츠 정체성과 무관한 검색 파라미터 — url_hash 계산 시 항상 제거.
# (반환되는 normalized(=fetch URL)에서는 제거하지 않는다.)
_ALWAYS_NOISE_PARAMS: frozenset[str] = frozenset({"searchWrd", "searchCnd"})

# 게시글/게시판 정체성 파라미터. 이것이 존재하면 menuNo는 단순 내비게이션 맥락이므로
# url_hash에서 제거한다 (동일 nttId가 여러 menuNo로 링크되는 eGov 중복 방지).
_CONTENT_ID_PARAMS: frozenset[str] = frozenset({"nttId", "bbsId"})

# menuNo는 조건부 노이즈다. nttId/bbsId 같은 더 강한 식별자가 있을 때만 노이즈로
# 취급하고, 그 외에는 정체성으로 보존한다. CMS 콘텐츠 페이지(contents.do?menuNo=…)는
# menuNo가 유일한 콘텐츠 식별자이므로, 이를 제거하면 서로 다른 페이지가 모두 같은
# url_hash로 붕괴되어 경로당 한 페이지만 저장되는 결함이 발생한다(찾아오시는길 등 누락).
_CONDITIONAL_NOISE_PARAM = "menuNo"

# eGov 게시판 경로 표식 — 이 경로의 페이지는 게시판 코드(path)+nttId/pageIndex로
# 정체성이 정해지므로 menuNo는 내비게이션 맥락에 불과하다.
_BOARD_PATH = "/bbs/"
# 상세(view.do)에서는 pageIndex도 정체성과 무관.
# 목록(list.do)에서는 페이지 커서이므로 유지해야 페이지네이션이 깨지지 않는다.
_DETAIL_PATH_SUFFIX = "view.do"
_DETAIL_ONLY_NOISE: frozenset[str] = frozenset({"pageIndex"})

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _identity_qs(path: str, qs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """콘텐츠 정체성 파라미터만 남긴다 — 내비/검색 노이즈(searchWrd/searchCnd,
    조건부 menuNo) + 상세 페이지의 pageIndex 제거. url_hash와 canonical_url이 공유하는
    단일 규칙(둘의 정체성 정의가 어긋나지 않도록)."""
    esafer_detail = path.endswith('/board.es') and any(
        k == 'list_no' and v for k, v in qs
    ) and ('act', 'view') in qs
    is_detail = path.endswith(_DETAIL_PATH_SUFFIX) or esafer_detail or any(
        k.lower() in ARTICLE_IDS and v for k, v in qs
    )
    # menuNo is noise when the content is identified by something else: an
    # nttId/bbsId in the query, or a board page whose identity is the board code
    # in the path (eGov `/bbs/{code}/list.do|view.do`). A bare CMS page
    # (contents.do?menuNo=…) has neither, so menuNo is its sole identity.
    menuno_is_noise = any(k in _CONTENT_ID_PARAMS for k, _ in qs) or _BOARD_PATH in path

    def _is_noise(k: str) -> bool:
        if k in _ALWAYS_NOISE_PARAMS:
            return True
        if k == _CONDITIONAL_NOISE_PARAM:
            return menuno_is_noise
        return is_detail and k in _DETAIL_ONLY_NOISE

    # SOMA path-based details carry list navigation state, not content identity.
    soma_detail = bool(
        re.fullmatch(
            r"/(?:dspy/(?:display|colect)|customer/notice|draw/notice|piece/product|class)/\d+(?:/[^/]+)*",
            path,
        )
    )
    has_detail_identity = soma_detail or is_detail or bool(re.search(r"/detail/[^/]+", path))
    navigation = {
        "page",
        "pageno",
        "npage",
        "pageindex",
        "form_page_index",
        "_form_id",
        "dummy",
        "form_page_list_count",
        "form_pc_page_count",
        "lastkey",
    } | CURSORS
    return [
        (k, v)
        for (k, v) in qs
        if not _is_noise(k) and not (has_detail_identity and k.lower() in navigation)
        and not (k.lower() == "topmenuseq" and any(
            name.lower() in BOARD_IDS for name, _ in qs
        ))
    ]


def _identity_hash(scheme: str, netloc: str, path: str, qs: list[tuple[str, str]]) -> str:
    """콘텐츠 정체성 기준 url_hash. normalized(fetch URL)는 건드리지 않는다.

    scheme(http/https)은 정체성에서 제외한다 — 동일 페이지의 http/https 변형이
    서로 다른 url_hash로 판정되어 이중 크롤·이중 적재되던 결함(코퍼스의 ~54%가
    scheme 쌍둥이)을 근절한다. normalized(fetch URL)의 scheme은 원형 유지한다.
    """
    ident = _identity_qs(path, qs)
    ident_url = urlunsplit(("", netloc, path, urlencode(ident), ""))
    return hashlib.sha1(ident_url.encode("utf-8")).hexdigest()


def canonical_url(raw: str) -> str:
    """콘텐츠 정체성 기준 canonical URL(스킴 유지). 같은 글의 URL 변형
    (pageIndex/searchWrd 차이)이 하나로 수렴하므로 SONAR source로 쓰면
    같은 글이 항상 같은 source → SONAR upsert가 중복을 방지한다.
    url_hash와 동일한 _identity_qs 규칙을 쓴다(정체성 정의 일원화)."""
    parts = urlsplit(raw.strip())
    # scheme은 https로 통일한다 — url_hash가 정체성에서 scheme을 제외하는 것과 동일
    # 취지로, 같은 페이지의 http/https 변형이 서로 다른 source로 이중 적재되는 것을 막는다.
    scheme = "https"
    netloc = parts.netloc.lower()
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if port == _DEFAULT_PORTS.get(scheme):
            netloc = host
    path = re.sub(r"/+", "/", parts.path or "/")
    qs = [
        (k, v)
        for (k, v) in query_pairs(parts.query)
        if k not in TRACKING_PARAMS
    ]
    ident = sorted(_identity_qs(path, qs), key=lambda kv: kv[0])
    return urlunsplit((scheme, netloc, path, urlencode(ident), ""))


def normalize_url(raw: str) -> tuple[str, str]:
    """returns (normalized_url, sha1_hash).

    1) scheme/host 소문자, 기본 포트(80/443) 제거, fragment 제거
    2) 경로 비면 '/' 추가 (외엔 trailing slash 보존)
    3) 쿼리: 알파벳 정렬 + TRACKING_PARAMS 제거 (PRESERVE_PARAMS는 항상 유지)
    4) 중복 슬래시 정규화
    5) url_hash = sha1(정체성 URL).hexdigest()  ← 40자.
       정체성 URL은 normalized에서 내비/검색 노이즈(menuNo/searchWrd/searchCnd)와
       상세 페이지의 pageIndex를 제거한 형태. normalized(fetch URL) 자체는 원형 유지.
    """
    parts = urlsplit(raw.strip())

    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()

    # default port 제거 (host:port 형식)
    if ":" in netloc:
        host, _, port = netloc.rpartition(":")
        if port == _DEFAULT_PORTS.get(scheme):
            netloc = host

    path = parts.path or "/"
    # 중복 슬래시 정규화 (단, scheme://는 영향 없음 — path만 처리)
    path = re.sub(r"/+", "/", path)

    # 쿼리: tracking 제거 + 정렬. value=None인 항목도 보존
    qs = query_pairs(parts.query)
    qs = [(k, v) for (k, v) in qs if k not in TRACKING_PARAMS]
    qs.sort(key=lambda kv: kv[0])
    new_query = urlencode(qs)

    # fragment 제거
    normalized = urlunsplit((scheme, netloc, path, new_query, ""))
    url_hash = _identity_hash(scheme, netloc, path, qs)
    return normalized, url_hash
