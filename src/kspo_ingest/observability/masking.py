"""로그 시크릿 마스킹.

OpenAI 키, Bearer/Basic auth, DB DSN password, Redis URL password, session 쿠키 값을
정규식 매칭하여 `***`로 치환. log 본문이 너무 길면 truncate.

호출처:
- observability.logger._serialize — 모든 JSON 로그가 sink로 가기 전 적용
- 다른 모듈에서 명시적으로 호출 가능
"""
from __future__ import annotations

import re
from re import Match, Pattern

# (compiled pattern, replacement function or static replacement string)
# 함수형 replacer는 group을 보존해야 하는 케이스(예: DSN의 host:port 보존, password만 마스킹)
_PATTERNS: list[tuple[Pattern[str], object]] = []


def _add(pat: Pattern[str], repl: object) -> None:
    _PATTERNS.append((pat, repl))


# OpenAI key — sk-... 또는 sk-proj-... 형태. project 키는 더 길고 하이픈/언더스코어 포함.
_add(re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9\-_]{16,}\b"), "***")

# Bearer / Basic auth header value
_add(
    re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._\-=+/]{16,}\b", re.IGNORECASE),
    lambda m: f"{m.group(1)} ***",
)

# postgresql+asyncpg://user:password@host... — password만 마스킹
_add(
    re.compile(r"(postgresql(?:\+\w+)?://[^:/\s]+:)([^@\s]+)(@)"),
    lambda m: f"{m.group(1)}***{m.group(3)}",
)

# redis://[user:]password@host
_add(
    re.compile(r"(redis://(?:[^:/\s]+:)?)([^@\s]+)(@)"),
    lambda m: f"{m.group(1)}***{m.group(3)}",
)

# session 쿠키 값 — `session=xxxx`
_add(
    re.compile(r"(\bsession=)([A-Za-z0-9._\-]{16,})"),
    lambda m: f"{m.group(1)}***",
)

# bcrypt 해시 — $2b$12$xxxxx 형태 (60자 고정)
_add(re.compile(r"\$2[aby]\$\d{2}\$[A-Za-z0-9./]{53}"), "***")


def mask(text: str, *, max_len: int = 8000) -> str:
    """모든 시크릿 패턴을 ***로 치환 후 길이 제한 적용.

    - 길이 max_len 초과 시 앞부분 + `...truncated...`
    - 패턴 미매치면 입력 그대로 반환
    """
    if not isinstance(text, str):
        return text
    if not text:
        return text

    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text) if callable(repl) else pat.sub(str(repl), text)

    if len(text) > max_len:
        text = text[:max_len] + "...truncated..."
    return text


def mask_match(m: Match[str]) -> str:
    """re.sub용 콜러블 — 첫 group만 ***로 치환."""
    return m.group(0).replace(m.group(1), "***", 1)
