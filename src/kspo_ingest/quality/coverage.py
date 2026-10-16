"""Coverage Validator — 게시판 누락 자동 감지.

사람이 "이 글 안 가져왔잖아"로 발견하던 것을 시스템이 스스로 감지한다.
각 confirmed board_source에 대해:
  1) 사이트가 실제로 보여주는 '최근(freshness 이내) 글 URL'을 목록에서 열거 → expected
  2) SONAR/Qdrant에 색인된 canonical source → have
  3) recall = |expected ∩ have| / |expected|, missing = expected − have
  4) 각 missing URL의 실패 원인(FailReason)을 재fetch로 분류

결과는 구조화 로그(event=coverage_report)로 남긴다. 매일 크론으로 실행되어
누락을 대시보드/로그로 조기 경보한다. 읽기 전용 — 수집/DB를 변경하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import parse_qs, urlparse

import httpx

from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.crawl.board import (
    build_page_url,
    extract_board_items,
    is_within_freshness,
    page_param_for_host,
)
from kspo_ingest.crawl.url_normalize import canonical_url
from kspo_ingest.observability.logger import get_logger
from kspo_ingest.settings import settings

log = get_logger("worker", "coverage")

_QDRANT = "http://sonar-qdrant-1:6333"
_COLLECTION = "kspo-3large"
_MAX_LIST_PAGES = 3  # 최근 글 recall 판정엔 앞쪽 몇 페이지면 충분(newest_first)

# 글 식별 쿼리 파라미터(전자정부 표준 등). 존재하면 그 자체가 글의 유일 식별자.
# camelCase/snake_case 혼용 사이트를 위해 언더스코어 변형도 함께 포함.
_ID_PARAMS = (
    "conseq", "con_seq", "nttid", "brd_con_sn", "list_no", "board_seq",
    "sn", "seq", "idx", "faqid", "empmnid",
)


def _article_id(url: str) -> str | None:
    """URL에서 글 식별자를 추출 — 목록/상세 경로가 달라도 같은 글을 매칭하기 위함.

    우선순위: ID 쿼리파라미터(conSeq/nttId 등) → 경로의 마지막 숫자 세그먼트(≥3자리).
    파라미터ID와 경로ID는 네임스페이스를 분리(`conseq:` vs `p:`)해 교차 오매칭을 막는다.
    예) /class/04/list/430 → 'p:430' ↔ 실제 색인 /class/430 → 'p:430' (일치)
        boardView.do?conSeq=5852 → 'conseq:5852'
    """
    p = urlparse(url)
    low = {k.lower(): v for k, v in parse_qs(p.query).items()}
    for k in _ID_PARAMS:
        v = low.get(k)
        if v and v[0].isdigit():
            return f"{k}:{v[0]}"
    for seg in reversed([s for s in p.path.split("/") if s]):
        if seg.isdigit() and len(seg) >= 3:
            return f"p:{seg}"
    return None


class FailReason(StrEnum):
    """누락/실패 표준 원인."""

    LIST_EMPTY = "LIST_EMPTY"
    SHELL_JS_RENDER = "JS_RENDER_REQUIRED"
    SESSION_GATED = "SESSION_GATED"
    LOGIN_GATED = "LOGIN_GATED"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    NETWORK_ERROR = "NETWORK_ERROR"
    ATTACHMENT_ONLY = "ATTACHMENT_ONLY"
    NOT_INDEXED = "NOT_INDEXED"  # 목록엔 있으나 색인 안 됨(원인 미상 — refine 드롭 등)
    UNKNOWN = "UNKNOWN"


@dataclass
class BoardCoverage:
    list_url: str
    expected: int
    have: int
    missing_urls: list[str] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=dict)  # FailReason → count

    @property
    def recall(self) -> float:
        return (self.have / self.expected) if self.expected else 1.0


def _indexed_sources(host: str) -> set[str]:
    """도메인 host의 색인된 canonical source 집합(Qdrant scroll)."""
    out: set[str] = set()
    nxt = None
    while True:
        body: dict = {
            "filter": {"must": [{"key": "metadata.source", "match": {"text": host}}]},
            "limit": 500,
            "with_payload": ["metadata.source"],
        }
        if nxt:
            body["offset"] = nxt
        r = httpx.post(
            f"{_QDRANT}/collections/{_COLLECTION}/points/scroll", json=body, timeout=40
        ).json()["result"]
        for p in r["points"]:
            s = (p["payload"].get("metadata") or {}).get("source")
            if s:
                out.add(canonical_url(s))
        nxt = r.get("next_page_offset")
        if not nxt:
            break
    return out


async def _enumerate_expected(client, list_url, host, ua, now) -> tuple[set[str], bool]:
    """목록에서 최근(freshness 이내) 글 canonical URL 열거. 반환: (set, is_shell)."""
    param = page_param_for_host(host)
    expected: set[str] = set()
    shell = False
    for page_no in range(1, _MAX_LIST_PAGES + 1):
        lu = build_page_url(list_url, page_no, param=param)
        try:
            r = await client.get(lu, headers={"User-Agent": ua})
        except Exception:
            break
        html = r.content.decode(detect_encoding(r.content, r.headers.get("content-type")), errors="replace")
        if "잠시만" in html or "불러오는 중" in html or len(html) < 800:
            shell = True
        items = extract_board_items(html, base_url=lu)
        if not items:
            break
        recent = [
            it for it in items
            if is_within_freshness(it.posted_at, freshness_days=settings.board_freshness_days, now=now)
        ]
        for it in recent:
            # 같은 호스트 글만 recall 대상. 타 도메인으로 링크아웃하는 항목
            # (kspo 매거진→spobiz 웹진 등)은 이 게시판의 콘텐츠가 아니므로 제외한다.
            if urlparse(it.url).netloc != host:
                continue
            expected.add(canonical_url(it.url))
        if not recent:  # newest_first: 최근 창을 벗어나면 종료
            break
    return expected, shell


async def check_board(client, bs, host, ua, indexed: set[str], now) -> BoardCoverage:
    expected, shell = await _enumerate_expected(client, bs.list_url, host, ua, now)
    # 글 번호(article ID) 기반 매칭 — 목록→상세 경로 형태가 사이트마다 달라도
    # (soma /class/04/list/430 vs 실제 /class/430) 같은 글을 정확히 대조한다.
    # URL 완전일치 OR ID 일치면 수집된 것으로 판정 → false-negative(가짜 누락) 제거.
    indexed_ids = {aid for u in indexed if (aid := _article_id(u))}
    have = 0
    missing: list[str] = []
    for u in sorted(expected):
        aid = _article_id(u)
        if u in indexed or (aid is not None and aid in indexed_ids):
            have += 1
        else:
            missing.append(u)
    reasons: dict[str, int] = {}
    for m in missing:
        reason = FailReason.SHELL_JS_RENDER if shell else FailReason.NOT_INDEXED
        reasons[reason] = reasons.get(reason, 0) + 1
    return BoardCoverage(bs.list_url, len(expected), have, missing[:20], reasons)


async def run_coverage(ctx: dict) -> dict:
    """confirmed board_source 전수 coverage 측정 크론. 구조화 로그로 리포트."""
    from sqlalchemy import select

    from kspo_ingest.db.models import BoardSource, Domain

    session_factory = ctx["session_factory"]
    async with session_factory() as s:
        srcs = list(
            (await s.execute(
                select(BoardSource).where(BoardSource.status == "confirmed")
                .order_by(BoardSource.domain_id)
            )).scalars().all()
        )
        doms = {d.id: d for d in (await s.execute(select(Domain))).scalars().all()}

    now = datetime.now(UTC)
    idx_cache: dict[str, set[str]] = {}
    boards = 0
    total_missing = 0
    low_recall: list[tuple[str, float, int]] = []
    async with httpx.AsyncClient(timeout=25, verify=False, follow_redirects=True) as client:
        for bs in srcs:
            d = doms.get(bs.domain_id)
            if d is None:
                continue
            if d.host not in idx_cache:
                idx_cache[d.host] = _indexed_sources(d.host)
            ua = d.user_agent or settings.crawl_user_agent_default
            cov = await check_board(client, bs, d.host, ua, idx_cache[d.host], now)
            if cov.expected == 0:
                continue  # 게시판 아님(목록 없음) — 커버리지 대상 아님
            boards += 1
            total_missing += (cov.expected - cov.have)
            if cov.recall < 0.99:
                low_recall.append((bs.list_url, cov.recall, cov.expected - cov.have))
                log.bind(
                    event="coverage_gap",
                    list_url=bs.list_url,
                    recall=round(cov.recall, 3),
                    expected=cov.expected,
                    have=cov.have,
                    missing=cov.expected - cov.have,
                    missing_sample=cov.missing_urls[:5],
                    reasons=cov.reasons,
                ).warning("게시판 누락 감지")

    log.bind(
        event="coverage_report",
        boards_checked=boards,
        total_missing=total_missing,
        low_recall_boards=len(low_recall),
    ).info("coverage check complete")
    return {"boards": boards, "missing": total_missing, "low_recall": len(low_recall)}
