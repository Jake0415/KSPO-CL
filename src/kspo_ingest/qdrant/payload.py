from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from kspo_ingest.qdrant.tags import build_tags
from kspo_ingest.settings import settings


@dataclass
class PayloadInput:
    chunk_id_sha1: str
    text_with_header: str  # Qdrant page_content
    source_url: str
    domain_host: str
    title: str | None
    summary: str | None
    keywords: list[str]
    posted_at: datetime | None
    is_attachment: bool
    attachment_id: int | None
    attachment_name: str | None
    attachment_download_url: str | None
    parent_page_id: int | None
    parent_page_url: str | None
    embedding_version: int
    keywords_extra: list[str] = field(default_factory=list)
    # Quality (Collection Architecture v2)
    quality_score: float = 0.0
    quadrant: str = "Q2"
    freshness_score: float = 0.0
    trust_score: float = 1.0


def build_payload(p: PayloadInput) -> dict[str, Any]:
    """LangChain Qdrant 어댑터 표준 — page_content + metadata{...}.

    PoC #1 결과로 키 컨벤션이 다르면 본 함수만 수정. 호출 측에서 key 가공 금지.
    """
    return {
        "page_content": p.text_with_header,
        "metadata": {
            "id": p.chunk_id_sha1,
            "source": p.source_url,
            "namespace": settings.kb_namespace,
            "type": "text",
            "domain_host": p.domain_host,
            "title": p.title,
            "summary": p.summary,
            "keywords": list(p.keywords),
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            "last_indexed_at": datetime.now(UTC).isoformat(),
            "is_attachment": p.is_attachment,
            "attachment_id": p.attachment_id,
            "attachment_name": p.attachment_name,
            "attachment_download_url": p.attachment_download_url,
            "parent_page_id": p.parent_page_id,
            "parent_page_url": p.parent_page_url,
            "embedding_version": p.embedding_version,
            "quality_score": p.quality_score,
            "quadrant": p.quadrant,
            "freshness_score": p.freshness_score,
            "trust_score": p.trust_score,
            "tags": build_tags(
                domain_host=p.domain_host,
                posted_at=p.posted_at,
                attachment_id=p.attachment_id,
                parent_page_id=p.parent_page_id,
                is_attachment=p.is_attachment,
                embedding_version=p.embedding_version,
            ),
        },
    }
