from __future__ import annotations

import base64
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from kspo_ingest.api.auth.password import verify_password
from kspo_ingest.api.auth.session import session_user
from kspo_ingest.db.session import async_session
from kspo_ingest.settings import settings


async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as s:
        yield s


async def require_admin(request: Request) -> str:
    """세션 우선, 실패 시 Basic Auth fallback. 둘 다 실패하면 401.

    M1.T1.3 시점의 fail-safe 503 placeholder를 본 Task에서 실 세션 인증으로 교체.
    """
    u = session_user(request)
    if u is not None:
        return u

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            raw = base64.b64decode(auth.split(" ", 1)[1]).decode()
            user, _, pw = raw.partition(":")
            if user == settings.admin_username and verify_password(pw):
                return user
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="unauthenticated",
        headers={"WWW-Authenticate": 'Basic realm="kspo-ingest"'},
    )


SessionDep = Depends(db_session)
AdminDep = Depends(require_admin)
