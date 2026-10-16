from __future__ import annotations

from kspo_ingest.clean.encoding import detect_encoding


def test_http_charset_takes_priority():
    raw = "안녕하세요".encode("euc-kr")
    enc = detect_encoding(raw, content_type="text/html; charset=euc-kr")
    assert enc.lower().replace("_", "-") == "euc-kr"


def test_meta_charset_fallback():
    body = '<html><head><meta charset="utf-8"></head><body>한국어</body></html>'.encode("utf-8")
    enc = detect_encoding(body, content_type="text/html")
    assert enc.lower().replace("_", "-") == "utf-8"


def test_bom_utf8_sig():
    raw = b"\xef\xbb\xbf<html><body>x</body></html>"
    enc = detect_encoding(raw, content_type=None)
    assert enc == "utf-8-sig"


def test_bom_utf16_le():
    raw = b"\xff\xfe<\x00h\x00t\x00m\x00l\x00>\x00"
    enc = detect_encoding(raw, content_type=None)
    assert enc == "utf-16"


def test_charset_normalizer_for_korean_cp949():
    raw = "공고 내용입니다. 한국어 본문 텍스트.".encode("cp949")
    enc = detect_encoding(raw, content_type=None)
    assert enc.lower().replace("_", "-") in {"cp949", "euc-kr"}


def test_fallback_to_utf8_when_all_fail():
    raw = b"plain ascii"
    enc = detect_encoding(raw, content_type=None)
    assert enc == "utf-8"


def test_invalid_charset_falls_through():
    """Content-Type charset이 잘못된 값이면 다음 단계로 fallthrough."""
    body = '<html><head><meta charset="utf-8"></head><body>x</body></html>'.encode("utf-8")
    enc = detect_encoding(body, content_type="text/html; charset=invalid-xxx")
    # invalid-xxx는 LookupError → meta로 fallthrough
    assert enc.lower().replace("_", "-") == "utf-8"
