"""Lossless, deterministic preparation of extracted text for RAG."""

from __future__ import annotations

import re
import unicodedata

from kspo_ingest.clean.numeric_text import numeric_to_words

VERSION = "rag-v7"
_NOISE = re.compile(
    r"^(?:조회수|조회)\s*[:：]?\s*[\d,]+$|^(?:목록으로|맨 위로|닫기|인쇄|공유하기)$"
)


def normalize_text(text: str) -> str:
    """Preserve facts, table separators and URLs; remove only explicit display noise."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\ufeff]", "", text)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        if not line or _NOISE.fullmatch(line):
            continue
        line = numeric_to_words(line)
        # Adjacent repeated labels only: distant repeated values may be meaningful.
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    return "\n".join(lines)


def preserve_references(refined: str, original: str) -> str:
    """Restore source image/attachment references omitted by a language model."""
    lines = normalize_text(refined).splitlines()
    original_lines = normalize_text(original).splitlines()
    for index, line in enumerate(original_lines):
        if "https://" in line or "http://" in line:
            if index and not original_lines[index - 1].startswith(("http://", "https://")):
                previous = original_lines[index - 1]
                if previous not in lines and ("첨부" in previous or "." in previous):
                    lines.append(previous)
            if line not in lines:
                lines.append(line)
    return "\n".join(lines)


def document_content(*, title: str, source_url: str, body: str, summary: str | None) -> str:
    """One source document; SONAR performs its configured token chunking afterwards."""
    parts = ["제목: " + normalize_text(title), "출처: " + source_url]
    body = normalize_text(body)
    if summary and normalize_text(summary) not in (normalize_text(title), body):
        parts.append("요약: " + normalize_text(summary))
    parts.append(body)
    return "\n\n".join(parts)


def enriched_content(original: str, enriched: str) -> str:
    """Keep extracted facts intact alongside explicitly labelled LLM preparation."""
    original = normalize_text(original)
    enriched = preserve_references(enriched, original)
    if not enriched or enriched == original:
        return original
    return "[원문 정보]\n" + original + "\n\n[LLM 정제·검색 보강]\n" + enriched
