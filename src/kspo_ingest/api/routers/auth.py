from __future__ import annotations

import base64

from fastapi import APIRouter, Form, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from kspo_ingest.api.auth.lockout import LoginLockout
from kspo_ingest.api.auth.password import (
    get_active_hash,
    hash_password,
    persist_new_hash,
    validate_password_complexity,
    verify_password,
)
from kspo_ingest.api.auth.session import session_login, session_logout, session_user
from kspo_ingest.api.deps import AdminDep
from kspo_ingest.settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_lockout = LoginLockout(
    max_attempts=settings.login_max_attempts,
    lockout_seconds=settings.login_lockout_seconds,
)


def _check_basic_header(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode()
        user, _, pw = raw.partition(":")
        if user == settings.admin_username and verify_password(pw):
            return user
    except Exception:
        return None
    return None


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
) -> dict:
    if _lockout.is_locked(username):
        remaining = _lockout.remaining_seconds(username)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"계정이 잠겼습니다. {remaining}초 후 다시 시도하세요.",
        )
    if username != settings.admin_username or not verify_password(password):
        _lockout.record_failure(username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    _lockout.record_success(username)
    session_login(request, username)
    return {"ok": True, "username": username}


@router.post("/logout")
async def logout(request: Request) -> Response:
    session_logout(request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    _admin: str = AdminDep,
) -> Response:
    """현재 비밀번호 검증 후 새 bcrypt 해시를 storage에 영속화.

    성공 후 기존 세션은 즉시 무효 — 사용자는 재로그인 필요.
    """
    if not verify_password(body.current_password, get_active_hash()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_current_password")
    try:
        validate_password_complexity(body.new_password)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    new_hash = hash_password(body.new_password)
    persist_new_hash(new_hash)
    session_logout(request)  # 보안 정책 — 비밀번호 변경 시 모든 세션 만료
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
async def me(request: Request) -> dict:
    u = session_user(request)
    if u is not None:
        return {"username": u, "via": "session"}
    basic_user = _check_basic_header(request)
    if basic_user is not None:
        return {"username": basic_user, "via": "basic"}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthenticated",
        headers={"WWW-Authenticate": 'Basic realm="kspo-ingest"'},
    )
