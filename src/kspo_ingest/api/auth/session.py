from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request

from kspo_ingest.settings import settings


def session_login(request: Request, username: str) -> None:
    request.session["admin"] = {
        "u": username,
        "iat": int(datetime.now(UTC).timestamp()),
    }


def session_logout(request: Request) -> None:
    request.session.pop("admin", None)


def session_user(request: Request) -> str | None:
    sess = request.session.get("admin")
    if not sess:
        return None
    iat = int(sess.get("iat", 0))
    age = int(datetime.now(UTC).timestamp()) - iat
    if age > settings.session_max_age_seconds:
        request.session.pop("admin", None)
        return None
    return sess.get("u")
