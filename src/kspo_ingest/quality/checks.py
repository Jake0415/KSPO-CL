"""Data reliability checks — 문서별 신뢰성 검증 함수.

각 check 함수는 독립적으로 실행 가능하며,
CheckResult를 반환한다 (status + score + detail + remedy).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from selectolax.parser import HTMLParser

from kspo_ingest.quality.scorer import _KOREAN_RE


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    score: float  # 0.0 ~ 1.0
    detail: str
    remedy: str = ""  # 수정 방법 제안


# --- 1. 본문 추출 품질 ---

_NAV_PATTERNS = re.compile(
    r"(?:홈\s*>\s*|메뉴\s*(?:열기|닫기|바로가기)|사이트맵|skip to|건너뛰기"
    r"|주메뉴|서브메뉴|네비게이션|전체메뉴|퀵메뉴)",
    re.IGNORECASE,
)
_FOOTER_PATTERNS = re.compile(
    r"(?:copyright|ⓒ|개인정보처리방침|이용약관|찾아오시는\s*길|우편번호|주소\s*:)",
    re.IGNORECASE,
)
_AD_PATTERNS = re.compile(
    r"(?:banner|advertisement|sponsored)",
    re.IGNORECASE,
)
_BROKEN_CHARS = re.compile(r"[�\ufffd]|\\x[0-9a-f]{2}|&#\d{4,};")
_DUPLICATE_LINE_RE = re.compile(r"^(.{20,})$", re.MULTILINE)


def check_boilerplate_removal(body_text: str, raw_html: str) -> CheckResult:
    """네비게이션/푸터/광고 잔여 확인.

    잔여 건수뿐 아니라 본문 대비 비율로 심각도 판단.
    본문이 1000자 이상이고 잔여가 소량이면 WARNING으로 완화.
    """
    issues: list[str] = []
    body_len = len(body_text)

    nav_matches = _NAV_PATTERNS.findall(body_text)
    footer_matches = _FOOTER_PATTERNS.findall(body_text)
    ad_matches = _AD_PATTERNS.findall(body_text)

    total_residue = len(nav_matches) + len(footer_matches) + len(ad_matches)

    if nav_matches:
        issues.append(f"네비게이션 잔여 {len(nav_matches)}건: {nav_matches[:3]}")
    if footer_matches:
        issues.append(f"푸터 잔여 {len(footer_matches)}건: {footer_matches[:3]}")
    if ad_matches:
        issues.append(f"광고 잔여 {len(ad_matches)}건")

    if not issues:
        return CheckResult("boilerplate_removal", CheckStatus.PASS, 1.0, "보일러플레이트 제거 정상")

    # 본문 대비 잔여 비율 — 본문이 충분하고 잔여가 소량이면 PASS
    if body_len >= 500 and total_residue <= 10:
        return CheckResult(
            "boilerplate_removal", CheckStatus.PASS,
            max(0.8, 1.0 - total_residue * 0.02),
            f"소량 잔여 ({total_residue}건, 본문 {body_len}자 대비 무시 가능)",
        )

    # 본문 대비 잔여 비율 기반 점수
    if body_len >= 1000:
        score = max(0.6, 1.0 - total_residue * 0.05)
    else:
        score = max(0.3, 1.0 - total_residue * 0.1)

    status = CheckStatus.WARNING if score >= 0.6 else CheckStatus.FAIL
    return CheckResult(
        "boilerplate_removal", status, score,
        "; ".join(issues),
        remedy="selector_blacklist에 해당 요소의 CSS selector 추가",
    )


def check_broken_chars(body_text: str) -> CheckResult:
    """깨진 문자/인코딩 오류 확인."""
    matches = _BROKEN_CHARS.findall(body_text)
    if not matches:
        return CheckResult("broken_chars", CheckStatus.PASS, 1.0, "인코딩 정상")

    ratio = len(matches) / max(len(body_text), 1)
    if ratio < 0.01:
        return CheckResult(
            "broken_chars", CheckStatus.WARNING, 0.8,
            f"깨진 문자 {len(matches)}건 (비율 {ratio:.4f})",
            remedy="인코딩 감지 로직 확인 (charset-normalizer fallback)",
        )
    return CheckResult(
        "broken_chars", CheckStatus.FAIL, max(0.0, 1.0 - ratio * 10),
        f"깨진 문자 {len(matches)}건 (비율 {ratio:.4f})",
        remedy="원본 HTML 인코딩 확인. EUC-KR/CP949 사이트일 가능성. encoding.py 수정 필요",
    )


def check_duplicate_lines(body_text: str) -> CheckResult:
    """본문 내 중복 문장 확인."""
    lines = [ln.strip() for ln in body_text.split("\n") if len(ln.strip()) > 20]
    if not lines:
        return CheckResult("duplicate_lines", CheckStatus.PASS, 1.0, "중복 없음")

    seen: dict[str, int] = {}
    for line in lines:
        seen[line] = seen.get(line, 0) + 1
    duplicates = {k: v for k, v in seen.items() if v > 1}

    if not duplicates:
        return CheckResult("duplicate_lines", CheckStatus.PASS, 1.0, "중복 없음")

    dup_count = sum(v - 1 for v in duplicates.values())
    ratio = dup_count / len(lines)
    score = max(0.0, 1.0 - ratio)

    if ratio < 0.1:
        return CheckResult(
            "duplicate_lines", CheckStatus.WARNING, score,
            f"중복 문장 {dup_count}건 / 전체 {len(lines)}줄",
        )
    return CheckResult(
        "duplicate_lines", CheckStatus.FAIL, score,
        f"중복 문장 {dup_count}건 / 전체 {len(lines)}줄",
        remedy="본문 추출 시 중복 제거 로직 추가 또는 selector_blacklist 확인",
    )


# --- 2. 데이터 완전성 ---

def check_completeness(
    *,
    title: str | None,
    body_text: str,
    posted_at: Any,
    summary: str | None,
    keywords: list[str],
    content_hash: str | None,
    crawl_only: bool = False,
) -> CheckResult:
    """필수 필드 누락 + 이상치 확인.

    crawl_only=True: 크롤 단계 검증 — LLM 후처리 필드(요약/키워드/hash)는 검사 제외.
    """
    issues: list[str] = []
    score = 1.0

    # 크롤 단계 필수 필드
    if not title or not title.strip():
        issues.append("제목 누락")
        score -= 0.2

    if not body_text or not body_text.strip():
        issues.append("본문 비어있음")
        score -= 0.5
    elif len(body_text) < 100:
        issues.append(f"본문 너무 짧음 ({len(body_text)}자)")
        score -= 0.2
    elif len(body_text) > 500_000:
        issues.append(f"본문 비정상적으로 김 ({len(body_text)}자)")
        score -= 0.1

    # 게시일 — 메인/목록 페이지에는 원래 없음. crawl_only에서는 감점 축소
    if posted_at is None:
        if crawl_only:
            pass  # 크롤 단계에서 게시일 없는 건 정상 (목록/메인 페이지)
        else:
            issues.append("게시일 누락")
            score -= 0.1

    # LLM 후처리 필드 — crawl_only 모드에서는 검사 생략
    if not crawl_only:
        if not summary or not summary.strip():
            issues.append("요약 누락")
            score -= 0.1
        if not keywords:
            issues.append("키워드 누락")
            score -= 0.05
        if not content_hash:
            issues.append("content_hash 누락")
            score -= 0.1

    score = max(0.0, score)
    if not issues:
        return CheckResult("completeness", CheckStatus.PASS, 1.0, "필드 완전성 정상")

    status = CheckStatus.WARNING if score >= 0.6 else CheckStatus.FAIL
    remedy_parts: list[str] = []
    if "제목 누락" in str(issues):
        remedy_parts.append("HTML <title> 또는 <h1> 태그 확인")
    if "본문 비어있음" in str(issues):
        remedy_parts.append("추출 방법 변경 (heuristic → trafilatura)")
    if "게시일 누락" in str(issues):
        remedy_parts.append("date_extract.py 패턴 추가")

    return CheckResult(
        "completeness", status, score,
        "; ".join(issues),
        remedy="; ".join(remedy_parts) if remedy_parts else "메타데이터 파싱 로직 확인",
    )


# --- 3. 원본-저장 일치 ---

def check_title_match(extracted_title: str | None, html: str) -> CheckResult:
    """추출된 제목과 HTML 원본 제목 비교."""
    tree = HTMLParser(html)
    html_title = None
    title_tag = tree.css_first("title")
    if title_tag:
        html_title = title_tag.text(strip=True)

    if not html_title and not extracted_title:
        return CheckResult("title_match", CheckStatus.WARNING, 0.5, "원본/추출 모두 제목 없음")

    if not html_title or not extracted_title:
        return CheckResult(
            "title_match", CheckStatus.WARNING, 0.3,
            f"불일치: 원본='{(html_title or '')[:50]}' 추출='{(extracted_title or '')[:50]}'",
            remedy="제목 추출 로직 확인 (_extract_title)",
        )

    # 정규화 비교
    norm_html = re.sub(r"\s+", " ", html_title).strip().lower()
    norm_ext = re.sub(r"\s+", " ", extracted_title).strip().lower()

    if norm_html == norm_ext:
        return CheckResult("title_match", CheckStatus.PASS, 1.0, "제목 일치")

    # 부분 일치 (제목에 사이트명 등 추가될 수 있음)
    if norm_ext in norm_html or norm_html in norm_ext:
        return CheckResult("title_match", CheckStatus.PASS, 0.9, "부분 일치 (원본 포함)")

    from difflib import SequenceMatcher
    sim = SequenceMatcher(None, norm_html, norm_ext).ratio()
    if sim >= 0.7:
        return CheckResult("title_match", CheckStatus.WARNING, sim, f"유사도 {sim:.2f}")

    return CheckResult(
        "title_match", CheckStatus.FAIL, sim,
        f"불일치: 원본='{html_title[:50]}' 추출='{extracted_title[:50]}' (유사도 {sim:.2f})",
        remedy="제목 추출 로직 수정 필요",
    )


def check_link_counts(body_text: str, html: str, host: str) -> CheckResult:
    """본문에서 발견된 링크 수 vs HTML 원본 비교."""
    tree = HTMLParser(html)
    html_links = 0
    internal_links = 0
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and not href.startswith(("#", "javascript:", "mailto:")):
            html_links += 1
            if href.startswith("/") or host in href:
                internal_links += 1

    return CheckResult(
        "link_counts", CheckStatus.PASS, 1.0,
        f"HTML 링크 {html_links}개 (내부 {internal_links}개)",
    )


# --- 4. 문서 길이 이상치 ---

def check_body_length(body_text: str) -> CheckResult:
    """본문 길이 이상치 확인."""
    length = len(body_text)

    if length == 0:
        return CheckResult(
            "body_length", CheckStatus.FAIL, 0.0,
            "본문 비어있음",
            remedy="추출 방법 확인 — Playwright 필요 여부 확인",
        )
    if length < 100:
        return CheckResult(
            "body_length", CheckStatus.FAIL, 0.2,
            f"비정상적으로 짧음 ({length}자)",
            remedy="JS redirect 또는 SPA 사이트 확인. SmartFetcher로 전환",
        )
    if length < 150:
        return CheckResult(
            "body_length", CheckStatus.WARNING, 0.5,
            f"짧은 본문 ({length}자) — 의미 있는 콘텐츠인지 확인 필요",
        )
    if length > 200_000:
        return CheckResult(
            "body_length", CheckStatus.WARNING, 0.7,
            f"매우 긴 본문 ({length}자) — 청킹 시 토큰 비용 높음",
        )
    return CheckResult("body_length", CheckStatus.PASS, 1.0, f"본문 길이 {length}자 정상")


# --- 5. 한국어 비율 ---


def check_korean_ratio(body_text: str, threshold: float = 0.3) -> CheckResult:
    """한국어 비율 확인.

    본문이 500자 이상이면 영문 전용 콘텐츠일 수 있으므로 FAIL→WARNING 완화.
    (sports.re.kr/global/main 같은 영문 사이트 대응)
    """
    chars = body_text.replace(" ", "").replace("\n", "")
    if not chars:
        return CheckResult("korean_ratio", CheckStatus.FAIL, 0.0, "본문 비어있음")

    korean = len(_KOREAN_RE.findall(body_text))
    ratio = korean / len(chars)

    if ratio >= threshold:
        return CheckResult("korean_ratio", CheckStatus.PASS, ratio, f"한국어 비율 {ratio:.1%}")

    # 본문이 충분하면 영문/숫자 위주 콘텐츠 — 유효한 콘텐츠로 PASS 처리
    # (공공기관 사이트의 영문 페이지, 통계 데이터 등)
    if len(body_text) >= 500:
        return CheckResult(
            "korean_ratio", CheckStatus.PASS, max(ratio, 0.5),
            f"영문/숫자 콘텐츠 ({ratio:.1%} 한국어, {len(body_text)}자)",
        )

    if ratio >= 0.1:
        return CheckResult(
            "korean_ratio", CheckStatus.WARNING, ratio,
            f"한국어 비율 낮음 {ratio:.1%} (본문 {len(body_text)}자)",
            remedy="짧은 영문 페이지 — 내용 확인 필요",
        )

    return CheckResult(
        "korean_ratio", CheckStatus.FAIL, ratio,
        f"한국어 거의 없음 {ratio:.1%}",
        remedy="비한국어 페이지 — drop 대상",
    )


# --- 통합 실행 ---

@dataclass
class DocumentCheckReport:
    """문서 1건의 전체 검증 결과."""
    page_id: int | None
    url: str
    checks: list[CheckResult] = field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.PASS
    overall_score: float = 0.0

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)
        # overall: 가장 나쁜 status
        if check.status == CheckStatus.FAIL:
            self.overall_status = CheckStatus.FAIL
        elif check.status == CheckStatus.WARNING and self.overall_status != CheckStatus.FAIL:
            self.overall_status = CheckStatus.WARNING
        # overall score: 가중 평균
        self._recalc_score()

    def _recalc_score(self) -> None:
        if not self.checks:
            self.overall_score = 0.0
            return
        self.overall_score = sum(c.score for c in self.checks) / len(self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.PASS)

    @property
    def warning_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.WARNING)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == CheckStatus.FAIL)

    @property
    def remedies(self) -> list[str]:
        return [c.remedy for c in self.checks if c.remedy]


def run_all_checks(
    *,
    page_id: int | None = None,
    url: str = "",
    raw_html: str,
    body_text: str,
    title: str | None,
    posted_at: Any = None,
    summary: str | None = None,
    keywords: list[str] | None = None,
    content_hash: str | None = None,
    host: str = "",
    crawl_only: bool = False,
) -> DocumentCheckReport:
    """문서 1건에 대해 모든 검증 실행.

    crawl_only=True: 크롤 단계 검증 — LLM 후처리 필드(요약/키워드/hash)는 검사 제외.
    """
    report = DocumentCheckReport(page_id=page_id, url=url)

    report.add(check_body_length(body_text))
    report.add(check_boilerplate_removal(body_text, raw_html))
    report.add(check_broken_chars(body_text))
    report.add(check_duplicate_lines(body_text))
    report.add(check_korean_ratio(body_text))
    report.add(check_title_match(title, raw_html))
    report.add(check_completeness(
        title=title, body_text=body_text, posted_at=posted_at,
        summary=summary, keywords=keywords or [], content_hash=content_hash,
        crawl_only=crawl_only,
    ))
    if host:
        report.add(check_link_counts(body_text, raw_html, host))

    return report
