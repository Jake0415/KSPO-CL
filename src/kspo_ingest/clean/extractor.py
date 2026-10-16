from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from selectolax.parser import HTMLParser

from kspo_ingest.clean.encoding import detect_encoding
from kspo_ingest.clean.selectors import apply_blacklist

ExtractionMethod = Literal["main_article", "trafilatura", "readability", "heuristic"]

MIN_BODY_LEN_FOR_ACCEPT = 200

# 본문이 아닌 태그 — 추출 전에 제거한다. selectolax의 node.text()는 script/style
# 내부 텍스트까지 포함하므로, 제거하지 않으면 인라인 JS/CSS가 본문에 섞여 한국어
# 비율을 왜곡(non_korean 오드롭)하고 정제·임베딩까지 오염시킨다.
_NOISE_TAGS = ("script", "style", "noscript", "template")


def _strip_noise_tags(html: str) -> str:
    tree = HTMLParser(html)
    tree.strip_tags(list(_NOISE_TAGS))
    return tree.html or html


@dataclass
class ExtractionResult:
    title: str | None
    body_text: str
    method: ExtractionMethod
    raw_html_decoded: str


_RE_INVISIBLE = re.compile(r"[​‌‍﻿ ]")


def _post_process(text: str) -> str:
    if not text:
        return text
    # 비가시 문자 제거
    text = _RE_INVISIBLE.sub(" ", text)
    # 공백 압축 (단락 경계 \n\n는 보존)
    paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in text.split("\n\n")]
    text = "\n\n".join(p for p in paragraphs if p)
    # 중복 라인 제거 (순서 유지, 20자 이상 라인만 대상)
    text = _dedup_lines(text)
    return text


def _dedup_lines(text: str) -> str:
    """연속되지 않아도 동일한 라인을 제거 (첫 출현만 유지).

    20자 미만 라인은 구조적 구분자일 수 있으므로 보존.
    spoinfo 74줄 중복, parktel 81줄 중복 해결.
    """
    lines = text.split("\n")
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if len(stripped) < 20:
            out.append(line)
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        out.append(line)
    return "\n".join(out)


def _extract_title(html: str) -> str | None:
    tree = HTMLParser(html)
    title_tag = tree.css_first("title")
    if title_tag and title_tag.text(strip=True):
        return title_tag.text(strip=True)
    h1 = tree.css_first("h1")
    if h1 and h1.text(strip=True):
        return h1.text(strip=True)
    return None


def _try_main_article(html: str) -> str:
    tree = HTMLParser(html)
    for sel in ("main", "article", "[role='main']"):
        node = tree.css_first(sel)
        if node:
            text = node.text(separator="\n").strip()
            if text:
                # 주의: node.text()는 표를 셀 단위 세로 나열로 풀어 행/열 결합을 잃는다.
                # 데이터 표가 있는 페이지는 extract()가 trafilatura를 먼저 시도한다.
                return _post_process(text)
    return ""


def _has_data_table(html: str) -> bool:
    """데이터 행이 있는 `<table>` 포함 여부.

    `<td>`가 하나라도 있으면 데이터 표로 본다(머리글만 있는 `<th>` 전용 표는 제외).
    레이아웃용 표를 오검출할 수 있으나, 그 경우에도 trafilatura 결과가
    MIN_BODY_LEN_FOR_ACCEPT를 넘지 못하면 기존 main_article 경로로 되돌아간다.
    """
    tree = HTMLParser(html)
    return any(tbl.css_first("td") is not None for tbl in tree.css("table"))


def _try_trafilatura(html: str) -> str:
    try:
        import trafilatura

        out = trafilatura.extract(html, favor_recall=True, include_tables=True, output_format="txt")
        return _post_process(out or "")
    except Exception:
        return ""


def _try_readability(html: str) -> str:
    try:
        from readability import Document

        doc = Document(html)
        summary_html = doc.summary()
        tree = HTMLParser(summary_html)
        body = tree.body
        if body is None:
            return ""
        text = body.text(separator="\n")
        return _post_process(text)
    except Exception:
        return ""


def _try_density(html: str) -> str:
    """텍스트 밀도 휴리스틱 — body 전체 텍스트 추출."""
    tree = HTMLParser(html)
    if tree.body is None:
        return ""
    text = tree.body.text(separator="\n")
    return _post_process(text)


def extract(
    raw: bytes, content_type: str | None = None, *, blacklist: list[str] | None = None
) -> ExtractionResult:
    """4단 우선순위로 본문 추출. 각 단계 실행 전 selector blacklist 적용."""
    encoding = detect_encoding(raw, content_type)
    html_decoded = raw.decode(encoding, errors="replace")

    cleaned_html = apply_blacklist(html_decoded, blacklist or [], None)
    cleaned_html = _strip_noise_tags(cleaned_html)
    title = _extract_title(cleaned_html)

    # 데이터 표가 있으면 trafilatura를 먼저 쓴다 — include_tables=True로 행/열을
    # 마크다운 파이프 표로 보존하기 때문. main_article(node.text)은 표를 세로 나열로
    # 풀어 "항목 ↔ 값" 결합을 잃는다(실측: 기금수입 표에서 8줄, 비공개대상정보에서 531줄
    # 떨어짐 → trafilatura는 둘 다 같은 줄).
    if _has_data_table(cleaned_html):
        body = _try_trafilatura(cleaned_html)
        if body and len(body) >= MIN_BODY_LEN_FOR_ACCEPT:
            return ExtractionResult(title, body, "trafilatura", html_decoded)

    body = _try_main_article(cleaned_html)
    if body and len(body) >= MIN_BODY_LEN_FOR_ACCEPT:
        return ExtractionResult(title, body, "main_article", html_decoded)

    body = _try_trafilatura(cleaned_html)
    if body and len(body) >= MIN_BODY_LEN_FOR_ACCEPT:
        return ExtractionResult(title, body, "trafilatura", html_decoded)

    body = _try_readability(cleaned_html)
    if body and len(body) >= MIN_BODY_LEN_FOR_ACCEPT:
        return ExtractionResult(title, body, "readability", html_decoded)

    body = _try_density(cleaned_html)
    return ExtractionResult(title, body or "", "heuristic", html_decoded)
