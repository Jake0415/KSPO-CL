from __future__ import annotations

import re

_BOM_UTF8 = b"\xef\xbb\xbf"
_BOM_UTF16_LE = b"\xff\xfe"
_BOM_UTF16_BE = b"\xfe\xff"


def _try_decode(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc, errors="strict")
        return True
    except (UnicodeDecodeError, LookupError):
        return False


def detect_encoding(raw: bytes, content_type: str | None = None) -> str:
    """5단계 우선순위로 인코딩 추정.

    1) HTTP Content-Type charset
    2) <meta charset="..."> (HTML 앞 4KB sniff)
    3) BOM
    4) charset_normalizer 추정
    5) '?' 비율 임계 초과 시 EUC-KR/CP949 재시도

    실패 시 utf-8 fallback.
    """
    # 1) HTTP charset
    if content_type:
        m = re.search(r"charset\s*=\s*([\w-]+)", content_type, re.IGNORECASE)
        if m:
            enc = m.group(1).strip().strip('"').strip("'")
            if _try_decode(raw, enc):
                return enc

    # 2) <meta charset>
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r'<meta[^>]+charset\s*=\s*["\']?([\w-]+)', head, re.IGNORECASE)
    if m:
        enc = m.group(1)
        if _try_decode(raw, enc):
            return enc

    # 3) BOM
    if raw.startswith(_BOM_UTF8):
        return "utf-8-sig"
    if raw.startswith(_BOM_UTF16_LE) or raw.startswith(_BOM_UTF16_BE):
        return "utf-16"

    # 4) charset_normalizer
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is not None and best.encoding:
            enc = best.encoding
            # ASCII is a subset of UTF-8; normalize for consistency
            if enc.lower() == "ascii":
                enc = "utf-8"
            if _try_decode(raw, enc):
                return enc
    except Exception:
        pass

    # 5) '?' 비율 임계 → 한국어 인코딩 재시도
    text = raw.decode("utf-8", errors="replace")
    if len(text) > 0 and text.count("?") / len(text) > 0.05:
        for enc in ("euc-kr", "cp949"):
            if _try_decode(raw, enc):
                return enc

    return "utf-8"
