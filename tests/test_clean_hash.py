from __future__ import annotations

from kspo_ingest.clean.hash import normalize_for_hash


def test_same_text_same_hash():
    a = normalize_for_hash("국민체육진흥공단 공고")
    b = normalize_for_hash("국민체육진흥공단 공고")
    assert a == b


def test_whitespace_differences_collapsed():
    a = normalize_for_hash("KSPO  \t공고\n\n  내용")
    b = normalize_for_hash("KSPO 공고 내용")
    assert a == b


def test_view_count_stripped():
    base = "공고 본문 내용입니다. 추가 설명도 있습니다."
    a = normalize_for_hash(f"{base} 조회수: 123")
    b = normalize_for_hash(f"{base} 조회수 4,567")
    c = normalize_for_hash(base)
    assert a == b == c


def test_today_date_stripped():
    a = normalize_for_hash("공고 내용 오늘날짜: 2026-05-07 끝")
    b = normalize_for_hash("공고 내용  오늘 날짜 : 2026-05-08 끝")
    assert a == b


def test_different_text_different_hash():
    a = normalize_for_hash("공고 A")
    b = normalize_for_hash("공고 B")
    assert a != b


def test_hash_is_64_hex_chars():
    h = normalize_for_hash("text")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
