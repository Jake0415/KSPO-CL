"""GET /api/settings/env — 환경변수 미러 (시크릿은 마스킹)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from kspo_ingest.api.deps import AdminDep
from kspo_ingest.observability.masking import mask
from kspo_ingest.settings import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


# 마스킹할 키 — 매스크 마커는 `***`로 치환되어 노출.
_SECRET_KEYS = {
    "admin_password_bcrypt",
    "session_secret",
    "postgres_password",
    "openai_api_key",
    "qdrant_api_key",
    "smtp_password",
}


class EnvEntry(BaseModel):
    key: str
    value: str
    masked: bool


class EnvMirrorOut(BaseModel):
    entries: list[EnvEntry]


@router.get("/env", response_model=EnvMirrorOut)
async def get_env_mirror(_admin: str = AdminDep) -> EnvMirrorOut:
    """Settings 객체를 dump하여 키·값 노출. 시크릿 키는 ***로 마스킹."""
    raw = settings.model_dump()
    entries: list[EnvEntry] = []
    for key, value in sorted(raw.items()):
        if value is None:
            text = ""
        elif isinstance(value, bool | int | float):
            text = str(value)
        else:
            text = str(value)
        if key in _SECRET_KEYS:
            entries.append(EnvEntry(key=key.upper(), value="***" if text else "", masked=True))
        else:
            entries.append(
                EnvEntry(key=key.upper(), value=mask(text) if text else "", masked=False)
            )
    return EnvMirrorOut(entries=entries)
