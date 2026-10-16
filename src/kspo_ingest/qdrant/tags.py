from __future__ import annotations

from datetime import datetime


def build_tags(
    *,
    domain_host: str,
    posted_at: datetime | None,
    attachment_id: int | None,
    parent_page_id: int | None,
    is_attachment: bool,
    embedding_version: int,
) -> list[str]:
    """Qdrant payload `metadata.tags`. v2.1 prefix만 사용 (Tier 2 prefix 추가 금지).

    포함:
      - `d:<host>`           — 도메인
      - `is_att:0|1`         — 첨부 여부
      - `v:<n>`              — embedding_version
      - `p:YYYY` / `p:YYYY-MM` (posted_at 있을 때만)
      - `att:<id>`           — 첨부 ID (첨부 청크일 때만)
      - `pid:<page_id>`      — 부모 페이지 ID (첨부 청크일 때만)
    """
    tags: list[str] = [
        f"d:{domain_host}",
        f"is_att:{int(is_attachment)}",
        f"v:{embedding_version}",
    ]
    if posted_at is not None:
        tags.append(f"p:{posted_at.year}")
        tags.append(f"p:{posted_at.year}-{posted_at.month:02d}")
    if attachment_id is not None:
        tags.append(f"att:{attachment_id}")
    if parent_page_id is not None:
        tags.append(f"pid:{parent_page_id}")
    return tags
