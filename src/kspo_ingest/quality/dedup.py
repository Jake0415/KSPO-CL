"""SimHash near-duplicate detection.

64-bit SimHash로 문서 유사도를 판단한다.
Hamming distance <= threshold(기본 3)이면 near-duplicate로 판정.
duplicate_score: 1.0(고유) ~ 0.0(완전 중복).
"""
from __future__ import annotations

import hashlib
import re


def simhash(text: str) -> int:
    """64-bit SimHash 계산."""
    tokens = _tokenize(text)
    if not tokens:
        return 0

    v = [0] * 64
    for token in tokens:
        h = _token_hash(token)
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    result = 0
    for i in range(64):
        if v[i] > 0:
            result |= 1 << i
    return result


def hamming_distance(a: int, b: int) -> int:
    """두 SimHash 간 Hamming distance."""
    return bin(a ^ b).count("1")


def compute_duplicate_score(
    doc_hash: int,
    existing_hashes: list[int],
    *,
    threshold: int = 3,
) -> float:
    """기존 문서 해시들과 비교하여 duplicate_score 반환.

    - 1.0: 완전 고유 (모든 기존 문서와 distance > threshold)
    - 0.0: 완전 중복 (distance == 0)
    - 중간값: 1.0 - (min_distance / threshold) 방식은 아니고,
      threshold 이하면 0.0, 초과면 1.0 (이진 판정)
    """
    if not existing_hashes:
        return 1.0

    min_dist = min(hamming_distance(doc_hash, h) for h in existing_hashes)
    if min_dist <= threshold:
        return 0.0
    return 1.0


_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    """2글자 이상 토큰 추출."""
    return _TOKEN_RE.findall(text.lower())


def _token_hash(token: str) -> int:
    """토큰의 64-bit hash."""
    digest = hashlib.md5(token.encode("utf-8")).digest()  # noqa: S324
    return int.from_bytes(digest[:8], "little")
