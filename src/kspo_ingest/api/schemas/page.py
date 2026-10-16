from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain_id: int
    url: str
    url_hash: str
    title: str | None = None
    status: str
    drop_reason: str | None = None
    http_status: int | None = None
    last_http_status: int | None = None
    content_type: str | None = None
    content_hash: str | None = None
    depth: int
    error_count: int
    discovered_at: datetime
    last_fetched_at: datetime | None = None
    last_indexed_at: datetime | None = None


class PageChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chunk_index: int
    is_attachment: bool
    attachment_id: int | None = None
    token_len: int
    embedding_model: str | None = None
    embed_status: str
    kb_status: str


class PageDetailOut(PageOut):
    chunks: list[PageChunkOut] = []
    attachments_count: int = 0
