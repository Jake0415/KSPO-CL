"""Admin 비밀번호 검증 + 변경 — bcrypt 4.x 직접 호출.

비밀번호 변경 후 새 bcrypt 해시는 `{storage_root}/admin_password.txt`에 저장된다.
다음 호출부터는 settings.admin_password_bcrypt(.env) 대신 이 파일 값이 우선.

단일 Admin 가정. 다중 운영자 도입 시 DB 테이블로 이전 (Tier 3).
"""
from __future__ import annotations

import re
from pathlib import Path

import bcrypt

from kspo_ingest.settings import settings


def validate_password_complexity(password: str) -> None:
    """Validate password meets public sector requirements.

    Rules (request_memo):
    - Minimum 8 characters
    - Must contain at least one letter (영문)
    - Must contain at least one digit (숫자)
    - Must contain at least one special character (특수문자)
    """
    if len(password) < 8:
        raise ValueError("비밀번호는 8자 이상이어야 합니다.")
    if not re.search(r"[a-zA-Z]", password):
        raise ValueError("비밀번호에 영문자가 포함되어야 합니다.")
    if not re.search(r"\d", password):
        raise ValueError("비밀번호에 숫자가 포함되어야 합니다.")
    if not re.search(r"[^a-zA-Z0-9]", password):
        raise ValueError("비밀번호에 특수문자가 포함되어야 합니다.")


def _override_path() -> Path:
    return Path(settings.storage_root) / "admin_password.txt"


def get_active_hash() -> str:
    """현재 유효한 bcrypt 해시. 파일 override 우선, 없으면 .env 값."""
    p = _override_path()
    if p.is_file():
        text = p.read_text(encoding="utf-8").strip()
        if text:
            return text
    return settings.admin_password_bcrypt


def verify_password(plain: str, bcrypt_hash: str | None = None) -> bool:
    """bcrypt_hash가 None이면 get_active_hash() 사용 (override 반영)."""
    h = bcrypt_hash if bcrypt_hash is not None else get_active_hash()
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), h.encode("ascii"))
    except (ValueError, TypeError):
        return False


def hash_password(plain: str) -> str:
    """새 bcrypt 해시 생성 (rounds=12)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def persist_new_hash(new_hash: str) -> None:
    """change-password 후 호출 — 다음 인증부터 새 해시 적용."""
    p = _override_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new_hash, encoding="utf-8")
