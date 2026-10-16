from __future__ import annotations

import hashlib
import uuid

NAMESPACE_KSPO = uuid.UUID("8c2a6e2e-0a3f-4b7d-9c54-1f1c5a2e1b00")


def chunk_id_sha1(
    page_id: int,
    embedding_version: int,
    chunk_index: int,
    is_attachment: bool,
    attachment_id: int | None,
) -> str:
    """결정론적 chunk id (40 hex). 같은 입력 → 같은 출력."""
    s = f"{page_id}|{embedding_version}|{chunk_index}|{int(is_attachment)}|{attachment_id or 0}"
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def to_qdrant_point_id(sha1_hex: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_KSPO, sha1_hex)
