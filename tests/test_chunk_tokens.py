from __future__ import annotations

from kspo_ingest.chunk.tokens import count_tokens, get_encoder


def test_korean_short_text():
    n = count_tokens("안녕하세요")
    assert n > 0


def test_empty_text_zero_tokens():
    assert count_tokens("") == 0


def test_idempotent():
    a = count_tokens("KSPO 공고 본문")
    b = count_tokens("KSPO 공고 본문")
    assert a == b


def test_lru_cache_returns_same_encoder_instance():
    e1 = get_encoder("cl100k_base")
    e2 = get_encoder("cl100k_base")
    assert e1 is e2
