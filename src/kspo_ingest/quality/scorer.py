"""Document quality scorer — 문서 품질 + 구조화 점수 산정 + Quadrant 자동 배정.

파이프라인 위치: refine_page 직후, chunk_and_index 직전에 호출.
refine 결과(refined_text, summary, keywords, is_meaningful)와
clean 결과(title, body_text, method, posted_at)를 입력으로 받아 점수 산정.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from kspo_ingest.quality.dedup import compute_duplicate_score, simhash

SCORER_VERSION = 2

# 한국어 음절 범위
_KOREAN_RE = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f\ua960-\ua97f]")


@dataclass
class ScorerInput:
    """스코어링에 필요한 입력."""

    title: str | None
    body_text: str
    extraction_method: str  # main_article, trafilatura, readability, heuristic
    posted_at: datetime | None
    summary: str | None
    keywords: list[str]
    is_meaningful: bool
    domain_host: str
    existing_simhashes: list[int] = field(default_factory=list)


@dataclass
class ScoreResult:
    """스코어링 결과."""

    quality_score: float
    structure_score: float
    freshness_score: float
    trust_score: float
    duplicate_score: float  # 1.0=고유, 0.0=중복
    simhash_value: int  # 64-bit SimHash (DB 저장용)
    quadrant: str  # Q1, Q2, Q3, Q4

    # detail fields for doc_quality table
    extraction_method: str
    body_length: int
    korean_ratio: float
    has_title: bool
    has_posted_at: bool
    has_summary: bool
    keyword_count: int


def score_document(inp: ScorerInput) -> ScoreResult:
    """문서 품질 + 구조화 점수 산정."""
    # --- Quality Score 구성 요소 ---

    # 1. 텍스트 길이 점수 (200자 미만=0, 500+=1.0)
    body_len = len(inp.body_text)
    if body_len < 200:
        text_len_score = 0.0
    elif body_len < 500:
        text_len_score = (body_len - 200) / 300
    else:
        text_len_score = 1.0

    # 2. 추출 방법 신뢰도
    method_scores = {
        "main_article": 1.0,
        "trafilatura": 0.8,
        "readability": 0.6,
        "heuristic": 0.3,
    }
    extraction_confidence = method_scores.get(inp.extraction_method, 0.5)

    # 3. 한국어 비율
    total_chars = len(inp.body_text.replace(" ", "").replace("\n", ""))
    if total_chars > 0:
        korean_chars = len(_KOREAN_RE.findall(inp.body_text))
        korean_ratio = korean_chars / total_chars
    else:
        korean_ratio = 0.0

    # 4. 최신성 (posted_at 기반 지수 감쇠)
    freshness = _compute_freshness(inp.posted_at)

    # 5. 의미성 (is_meaningful)
    meaningful_score = 1.0 if inp.is_meaningful else 0.0

    # Quality = weighted average
    quality_score = _weighted_avg(
        [
            (text_len_score, 2.0),
            (extraction_confidence, 1.5),
            # Language ratio is diagnostic only; multilingual documents are not penalized.
            (freshness, 1.0),
            (meaningful_score, 2.0),
        ]
    )

    # --- Structure Score 구성 요소 ---
    has_title = bool(inp.title and len(inp.title.strip()) > 2)
    has_posted_at = inp.posted_at is not None
    has_summary = bool(inp.summary and len(inp.summary.strip()) > 10)
    kw_count = len(inp.keywords)
    kw_score = min(kw_count / 10, 1.0)  # 10개 이상이면 1.0

    structure_score = _weighted_avg(
        [
            (1.0 if has_title else 0.0, 2.0),
            (1.0 if has_posted_at else 0.0, 1.5),
            (1.0 if has_summary else 0.0, 2.0),
            (kw_score, 1.0),
        ]
    )

    # --- Trust Score (도메인 기반) ---
    trust_score = _domain_trust(inp.domain_host)

    # --- Duplicate Score (SimHash) ---
    doc_hash = simhash(inp.body_text)
    dup_score = compute_duplicate_score(
        doc_hash,
        inp.existing_simhashes,
    )

    # --- Quadrant 배정 ---
    quadrant = _assign_quadrant(quality_score, structure_score)

    return ScoreResult(
        quality_score=round(quality_score, 3),
        structure_score=round(structure_score, 3),
        freshness_score=round(freshness, 3),
        trust_score=round(trust_score, 3),
        duplicate_score=dup_score,
        simhash_value=doc_hash,
        quadrant=quadrant,
        extraction_method=inp.extraction_method,
        body_length=body_len,
        korean_ratio=round(korean_ratio, 3),
        has_title=has_title,
        has_posted_at=has_posted_at,
        has_summary=has_summary,
        keyword_count=kw_count,
    )


def _weighted_avg(items: list[tuple[float, float]]) -> float:
    total_w = sum(w for _, w in items)
    if total_w == 0:
        return 0.0
    return sum(v * w for v, w in items) / total_w


def _compute_freshness(posted_at: datetime | None) -> float:
    """최신성 점수. posted_at 없으면 0.5 (중립). 감쇠: 1년마다 0.15 감소."""
    if posted_at is None:
        return 0.5

    now = datetime.now(UTC)
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    age_days = (now - posted_at).days
    if age_days < 0:
        return 1.0  # 미래 날짜 → 최신
    if age_days <= 90:
        return 1.0
    if age_days <= 365:
        return 1.0 - (age_days - 90) / 365 * 0.3  # 0.7~1.0
    # 1년 이상: 연간 0.15 감쇠, 최소 0.1
    years = age_days / 365
    return max(0.1, 1.0 - years * 0.15)


def _domain_trust(host: str) -> float:
    """도메인 신뢰도. KSPO 패밀리는 1.0, 그 외 0.7."""
    trusted_suffixes = (
        "kspo.or.kr",
        "sports.re.kr",
        "ksponco.or.kr",
        "kcycle.or.kr",
        "kboat.or.kr",
        "spoex.com",
        "spoinfo.or.kr",
        "parktel.co.kr",
        "ecolian.or.kr",
    )
    host_lower = host.lower()
    for suffix in trusted_suffixes:
        if host_lower == suffix or host_lower.endswith("." + suffix):
            return 1.0
    return 0.7


def _assign_quadrant(quality: float, structure: float) -> str:
    """Quadrant 배정."""
    if quality >= 0.6 and structure >= 0.6:
        return "Q1"  # PUBLISH
    if quality >= 0.6 and structure < 0.6:
        return "Q2"  # ENRICH FIRST
    if quality < 0.6 and structure >= 0.4:
        return "Q3"  # RE-CRAWL
    return "Q4"  # ARCHIVE
