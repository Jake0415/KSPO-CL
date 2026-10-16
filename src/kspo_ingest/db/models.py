from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import (
    ARRAY,
    JSONB,
    TIMESTAMP,
)
from sqlalchemy.dialects.postgresql import (
    UUID as PG_UUID,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kspo_ingest.db.base import Base


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(Text, unique=True)
    scheme: Mapped[str] = mapped_column(Text, server_default="https")
    start_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    max_depth: Mapped[int] = mapped_column(Integer, server_default="10")
    max_pages: Mapped[int] = mapped_column(Integer, server_default="30000")
    rate_limit_rps: Mapped[Decimal] = mapped_column(Numeric, server_default="1.5")
    concurrency: Mapped[int] = mapped_column(Integer, server_default="4")
    use_playwright: Mapped[bool] = mapped_column(Boolean, server_default="false")
    respect_robots: Mapped[bool] = mapped_column(Boolean, server_default="true")
    user_agent: Mapped[str | None] = mapped_column(Text)
    allow_patterns: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    deny_patterns: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    selector_blacklist: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    incremental_cron: Mapped[str | None] = mapped_column(Text, server_default="0 3 * * 0")
    incremental_enabled: Mapped[bool | None] = mapped_column(Boolean, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    # passive_deletes=True — DB의 ON DELETE CASCADE에 위임. SQLAlchemy가 자손을 미리
    # 로드해서 SET NULL 시도하지 않도록 막는다 (NOT NULL 컬럼이라 IntegrityError 발생).
    pages: Mapped[list[Page]] = relationship(
        back_populates="domain", cascade="all, delete", passive_deletes=True
    )
    crawl_jobs: Mapped[list[CrawlJob]] = relationship(
        back_populates="domain", cascade="all, delete", passive_deletes=True
    )


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(Text)               # full | incremental | url_refresh
    seed_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # PENDING | RUNNING | SUCCESS | FAILED | CANCELLED
    status: Mapped[str] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(Text, server_default="admin")
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    stats: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    arq_job_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    domain: Mapped[Domain] = relationship(back_populates="crawl_jobs")


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        UniqueConstraint("domain_id", "url_hash", name="uq_pages_domain_id_url_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(CHAR(40))
    http_status: Mapped[int | None] = mapped_column(Integer)
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(CHAR(64))
    title: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    depth: Mapped[int] = mapped_column(Integer, server_default="0")
    discovered_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_indexed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    board_source_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("board_source.id", ondelete="SET NULL")
    )
    drop_reason: Mapped[str | None] = mapped_column(Text)
    error_count: Mapped[int] = mapped_column(Integer, server_default="0")
    storage_paths: Mapped[dict | None] = mapped_column(JSONB)

    domain: Mapped[Domain] = relationship(back_populates="pages")


class BoardSource(Base):
    __tablename__ = "board_source"
    __table_args__ = (
        UniqueConstraint(
            "domain_id", "list_url", name="uq_board_source_domain_list_url"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    list_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="candidate")
    validation_error: Mapped[str | None] = mapped_column(Text)
    newest_first: Mapped[bool] = mapped_column(Boolean, server_default="true")
    detected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_refreshed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("domain_id", "file_hash", name="uq_attachments_domain_id_file_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pages.id", ondelete="CASCADE"))
    domain_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    source_url: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    file_hash: Mapped[str] = mapped_column(CHAR(64))
    storage_path: Mapped[str] = mapped_column(Text)
    text_path: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "page_id",
            "embedding_version",
            "chunk_index",
            "is_attachment",
            "attachment_id",
            name="uq_chunks_page_ver_idx_attach",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_id_sha1: Mapped[str] = mapped_column(CHAR(40))
    qdrant_point_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    page_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pages.id", ondelete="CASCADE"))
    attachment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="CASCADE")
    )
    is_attachment: Mapped[bool] = mapped_column(Boolean, server_default="false")
    chunk_index: Mapped[int] = mapped_column(Integer)
    token_len: Mapped[int] = mapped_column(Integer)
    embedding_model: Mapped[str] = mapped_column(Text)
    embedding_version: Mapped[int] = mapped_column(Integer, server_default="1")
    embed_status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    kb_status: Mapped[str] = mapped_column(Text, server_default="PENDING")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    page_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="CASCADE")
    )
    attachment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("attachments.id", ondelete="CASCADE")
    )
    job_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("crawl_jobs.id", ondelete="CASCADE")
    )
    purpose: Mapped[str] = mapped_column(Text)                # refine | embedding
    model: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )


class KpiSnapshot(Base):
    """일별 KPI 누적 (M5.T5.4 cron_kpi_daily가 INSERT). domain_id NULL = 전체 합산."""

    __tablename__ = "kpi_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    measured_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    domain_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("domains.id", ondelete="CASCADE")
    )
    coverage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    avg_freshness_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    job_success_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    monthly_cost_krw: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    indexed_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    dropped_count: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_count: Mapped[int] = mapped_column(BigInteger, server_default="0")


class DocQuality(Base):
    """문서 품질 평가 — Quadrant 자동 분류 + publish 게이트 판단."""

    __tablename__ = "doc_quality"

    page_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True
    )
    # Quality scores (0.000 ~ 1.000)
    quality_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0")
    structure_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0")
    freshness_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0")
    trust_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="1.0")
    importance_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0")
    duplicate_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="1.0")
    # Quadrant: Q1 (publish), Q2 (enrich), Q3 (re-crawl), Q4 (archive)
    quadrant: Mapped[str] = mapped_column(Text, server_default="Q2")
    # Extraction quality details
    extraction_method: Mapped[str | None] = mapped_column(Text)
    body_length: Mapped[int] = mapped_column(Integer, server_default="0")
    korean_ratio: Mapped[Decimal] = mapped_column(Numeric(4, 3), server_default="0")
    has_title: Mapped[bool] = mapped_column(Boolean, server_default="false")
    has_posted_at: Mapped[bool] = mapped_column(Boolean, server_default="false")
    has_summary: Mapped[bool] = mapped_column(Boolean, server_default="false")
    keyword_count: Mapped[int] = mapped_column(Integer, server_default="0")
    # Versioning
    scorer_version: Mapped[int] = mapped_column(Integer, server_default="1")
    scored_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


class QaLog(Base):
    """챗봇 질의응답 로그 — 미응답·오류 관리 + 만족도 통계."""

    __tablename__ = "qa_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    sources: Mapped[dict | None] = mapped_column(JSONB)  # [{source, title, score}]
    is_answered: Mapped[bool] = mapped_column(Boolean, server_default="true")
    error_message: Mapped[str | None] = mapped_column(Text)
    satisfaction: Mapped[int | None] = mapped_column(Integer)  # 1-5 scale
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(Text)  # openai | gemini
    model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
