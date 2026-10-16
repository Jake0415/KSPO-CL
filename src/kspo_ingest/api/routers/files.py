"""GET /files/{attachment_id} — 챗봇 사용자에게 노출되는 공개 다운로드 링크.

v2.0 Lite: 파일을 직접 보관하지 않으므로 attachments.source_url로 302 redirect.
인증 없음 (T1.4 require_admin 미적용) — 챗봇이 외부 사용자에게 직접 노출하는 화이트리스트.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from kspo_ingest.api.deps import SessionDep
from kspo_ingest.db.models import Attachment

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{attachment_id}")
async def download_attachment(
    attachment_id: int, s: AsyncSession = SessionDep
) -> RedirectResponse:
    att = await s.get(Attachment, attachment_id)
    if att is None or not att.source_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attachment not found")
    return RedirectResponse(url=att.source_url, status_code=status.HTTP_302_FOUND)
