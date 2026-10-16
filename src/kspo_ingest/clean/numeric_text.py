"""Convert recognized numeric notation without corrupting identifiers or references."""

from __future__ import annotations

import re
from datetime import date

_PROTECTED = re.compile(
    r"https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
    r"|(?<!\d)(?:0\d{1,2}|1[568]\d{2})-\d{3,4}(?:-\d{4})?(?!\d)"
    r"|[^\s/]+\.(?:pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip|jpg|png)(?!\w)",
    re.I,
)
_DATE = re.compile(r"(?<![\w.])((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})\.?(?!\d)")
_RANGE = r"\s*[~～∼–—-]\s*"
_UNIT = r"(?:퍼센트|개월|시간|분|세|살|년|월|일|시|원|명|회|개|미터|킬로그램)"


def _date_words(match: re.Match) -> str:
    year, month, day = map(int, match.groups())
    try:
        date(year, month, day)
    except ValueError:
        return match.group(0)
    return f"{year}년 {month}월 {day}일"


def _convert(text: str) -> str:
    text = _DATE.sub(_date_words, text)
    # Valid dates and clock times before numeric hyphen ranges.
    text = re.sub(
        r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", lambda m: f"{int(m[1])}시 {int(m[2])}분", text
    )
    text = re.sub(r"(?<=\d)\s*[%％]", "퍼센트", text)
    text = re.sub(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)", lambda m: m[0].replace(",", ""), text)
    endpoint = r"(?:\d{4}년\s*)?(?:\d{1,2}월\s*)?\d{1,2}일"
    text = re.sub(f"({endpoint}){_RANGE}({endpoint})", r"\1부터 \2까지", text)
    clock = r"\d{1,2}시(?:\s*\d{1,2}분)?"
    text = re.sub(f"({clock}){_RANGE}({clock})", r"\1부터 \2까지", text)
    number = r"\d+(?:\.\d+)?"

    def range_words(match: re.Match) -> str:
        left, left_unit, right, right_unit = match.groups()
        left_unit = left_unit or right_unit or ""
        right_unit = right_unit or left_unit
        return f"{left}{left_unit}부터 {right}{right_unit}까지"

    text = re.sub(
        rf"(?<![\w.\-])({number})\s*({_UNIT})?{_RANGE}({number})\s*({_UNIT})?(?![\w.\-])",
        range_words,
        text,
    )
    text = re.sub(rf"[≥≧]\s*({number})\s*({_UNIT})?", r"\1\2 이상", text)
    text = re.sub(rf"[≤≦]\s*({number})\s*({_UNIT})?", r"\1\2 이하", text)
    # Decimal punctuation becomes spoken notation in recognized quantities only.
    text = re.sub(rf"(?<![\w.])(\d+)\.(\d+)(?=\s*{_UNIT}|부터|까지)", r"\1점\2", text)
    return text


def numeric_to_words(text: str) -> str:
    """URLs, filenames, phones and email remain verbatim; numeric facts retain values."""
    parts: list[str] = []
    offset = 0
    for match in _PROTECTED.finditer(text):
        parts.extend([_convert(text[offset : match.start()]), match[0]])
        offset = match.end()
    parts.append(_convert(text[offset:]))
    return "".join(parts)
