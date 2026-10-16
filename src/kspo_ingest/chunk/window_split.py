from __future__ import annotations

import re

from kspo_ingest.chunk.tokens import count_tokens, get_encoder

_SENTENCE_RE = re.compile(r"(?<=[\.!?。])\s+")


def _split_to_units(text: str) -> list[str]:
    """단락 → 줄 → 문장 → 어절 순으로 분해. 빈 토큰 제거."""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if count_tokens(para) <= 0:
            continue
        # 단락 자체를 우선 단위로
        units.append(para)
    if not units and text.strip():
        units = [text.strip()]
    return units


def _split_long_unit(unit: str, max_tokens: int) -> list[str]:
    """단위가 max_tokens 초과면 줄 → 문장 → 어절 단위로 재분해."""
    if count_tokens(unit) <= max_tokens:
        return [unit]

    # 줄 단위
    lines = [ln for ln in unit.split("\n") if ln.strip()]
    if len(lines) > 1:
        out: list[str] = []
        for ln in lines:
            out.extend(_split_long_unit(ln, max_tokens))
        return out

    # 문장 단위
    sentences = _SENTENCE_RE.split(unit)
    if len(sentences) > 1:
        out2: list[str] = []
        for s in sentences:
            out2.extend(_split_long_unit(s, max_tokens))
        return out2

    # 어절 단위
    words = unit.split()
    if len(words) > 1:
        # 토큰 수 기준 그리디 누적
        out3: list[str] = []
        buf: list[str] = []
        for w in words:
            buf.append(w)
            if count_tokens(" ".join(buf)) > max_tokens:
                buf.pop()
                if buf:
                    out3.append(" ".join(buf))
                buf = [w]
        if buf:
            out3.append(" ".join(buf))
        return out3

    # 단일 토큰 텍스트가 max를 넘으면(매우 드묾) 토큰 수로 강제 분할
    enc = get_encoder()
    ids = enc.encode(unit)
    chunks: list[str] = []
    for i in range(0, len(ids), max_tokens):
        chunks.append(enc.decode(ids[i : i + max_tokens]))
    return chunks


def window_split(text: str, *, target: int, overlap: int) -> list[str]:
    """target 토큰 그리디 누적, 청크 간 overlap 토큰 prepend.

    1) 단락 단위로 합쳐 target 도달 시 cut
    2) 한 단락이 target 초과 → 줄/문장/어절로 재분해
    3) 청크[i+1] 앞에 청크[i] 끝 overlap 토큰 prepend
    """
    if target <= 0:
        return [text]

    units = _split_to_units(text)
    pieces: list[str] = []
    for u in units:
        pieces.extend(_split_long_unit(u, target))

    enc = get_encoder()

    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0

    for piece in pieces:
        piece_tokens = count_tokens(piece)
        # 더 추가할 수 없으면 flush
        if buf and buf_tokens + piece_tokens > target:
            chunks.append("\n\n".join(buf))
            buf = []
            buf_tokens = 0
        buf.append(piece)
        buf_tokens += piece_tokens

    if buf:
        chunks.append("\n\n".join(buf))

    if overlap <= 0 or len(chunks) < 2:
        return chunks

    # overlap 적용 — 청크[i] 끝 overlap 토큰을 청크[i+1] 앞에 prepend
    out: list[str] = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_ids = enc.encode(chunks[i - 1])
        tail_ids = prev_ids[-overlap:] if len(prev_ids) >= overlap else prev_ids
        tail_text = enc.decode(tail_ids).strip()
        if tail_text:
            out.append(tail_text + "\n\n" + chunks[i])
        else:
            out.append(chunks[i])
    return out
