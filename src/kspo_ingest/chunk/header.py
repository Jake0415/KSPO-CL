from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class PageHeaderInput:
    title: str | None
    domain_host: str
    posted_at: datetime | None
    summary: str | None


def build_page_header(h: PageHeaderInput) -> str:
    """페이지 청크용 헤더. posted_at/summary 없으면 해당 라인 생략."""
    lines: list[str] = []
    if h.title:
        lines.append(f"[제목] {h.title}")
    lines.append(f"[도메인] {h.domain_host}")
    if h.posted_at:
        lines.append(f"[게시일] {h.posted_at.date().isoformat()}")
    if h.summary:
        lines.append(f"[요약] {h.summary}")
    return "\n".join(lines) + "\n\n— 본문 —\n"


@dataclass
class AttachmentHeaderInput:
    file_name: str
    parent_title: str | None
    parent_posted_at: datetime | None


def build_attachment_header(h: AttachmentHeaderInput) -> str:
    """첨부 청크용 별도 헤더 (`docs/design/03_chunk_embed_qdrant.md` §3.4)."""
    lines: list[str] = [f"[첨부파일] {h.file_name}"]
    if h.parent_title:
        lines.append(f"[부모 게시글] {h.parent_title}")
    if h.parent_posted_at:
        lines.append(f"[게시일] {h.parent_posted_at.date().isoformat()}")
    return "\n".join(lines) + "\n\n— 본문 —\n"
