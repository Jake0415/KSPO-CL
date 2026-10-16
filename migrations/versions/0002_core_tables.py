"""core tables — 6 tables (domains, crawl_jobs, pages, attachments, chunks, llm_usage)

Revision ID: 0002_core_tables
Revises: 0001_init
Create Date: 2026-05-07

본 마이그레이션은 docs/design/_appendix.md §A DDL을 미러한다.

FK 의존 그래프 분석 결과 순환이 없으므로 (domains → {crawl_jobs, pages, attachments};
pages → {attachments, chunks, llm_usage}; attachments → {chunks, llm_usage};
crawl_jobs → llm_usage) 단일 op.create_table 시퀀스로 생성 가능하다.
부록 §A 끝의 "외래키 순환 참조" 주석은 v1.0 잔재이며 v2.0 DDL에는 적용되지 않는다.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_core_tables"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) domains
    op.create_table(
        "domains",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("host", sa.Text, nullable=False, unique=True),
        sa.Column("scheme", sa.Text, nullable=False, server_default="https"),
        sa.Column("display_name", sa.Text),
        sa.Column("max_depth", sa.Integer, nullable=False, server_default="10"),
        sa.Column("max_pages", sa.Integer, nullable=False, server_default="20000"),
        sa.Column("rate_limit_rps", sa.Numeric, nullable=False, server_default="1.5"),
        sa.Column("concurrency", sa.Integer, nullable=False, server_default="4"),
        sa.Column("use_playwright", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("respect_robots", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("user_agent", sa.Text),
        sa.Column("allow_patterns", sa.ARRAY(sa.Text)),
        sa.Column("deny_patterns", sa.ARRAY(sa.Text)),
        sa.Column("selector_blacklist", sa.ARRAY(sa.Text)),
        sa.Column("incremental_cron", sa.Text, server_default="0 3 * * 0"),
        sa.Column("incremental_enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 2) crawl_jobs
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger, sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("job_type", sa.Text, nullable=False),  # full | incremental | url_refresh
        sa.Column("seed_urls", sa.ARRAY(sa.Text)),
        sa.Column("status", sa.Text, nullable=False),  # PENDING|RUNNING|SUCCESS|FAILED|CANCELLED
        sa.Column("triggered_by", sa.Text, nullable=False, server_default="admin"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("stats", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("arq_job_id", sa.Text),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_jobs_status", "crawl_jobs", ["status"])
    op.create_index("idx_jobs_domain", "crawl_jobs", ["domain_id"])

    # 3) pages
    op.create_table(
        "pages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger, sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("url_hash", sa.CHAR(40), nullable=False),
        sa.Column("http_status", sa.Integer),
        sa.Column("last_http_status", sa.Integer),
        sa.Column("content_type", sa.Text),
        sa.Column("content_hash", sa.CHAR(64)),
        sa.Column("title", sa.Text),
        sa.Column("depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discovered_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_fetched_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_indexed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("drop_reason", sa.Text),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("storage_paths", postgresql.JSONB),
        sa.UniqueConstraint("domain_id", "url_hash", name="uq_pages_domain_id_url_hash"),
    )
    op.create_index("idx_pages_status", "pages", ["status"])
    op.create_index("idx_pages_domain", "pages", ["domain_id"])

    # 4) attachments
    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "page_id",
            sa.BigInteger,
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain_id", sa.BigInteger, sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("file_name", sa.Text),
        sa.Column("mime_type", sa.Text),
        sa.Column("byte_size", sa.BigInteger),
        sa.Column("file_hash", sa.CHAR(64), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("text_path", sa.Text),
        sa.Column("extracted_text", sa.Text),
        sa.Column("extraction_status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("domain_id", "file_hash", name="uq_attachments_domain_id_file_hash"),
    )
    op.create_index("idx_attachments_page", "attachments", ["page_id"])

    # 5) chunks — FK 둘 다 한 번에 (attachments는 위에서 이미 생성됨)
    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("chunk_id_sha1", sa.CHAR(40), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "page_id",
            sa.BigInteger,
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.BigInteger,
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
        ),
        sa.Column("is_attachment", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("token_len", sa.Integer, nullable=False),
        sa.Column("embedding_model", sa.Text, nullable=False),
        sa.Column("embedding_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("embed_status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("kb_status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "page_id",
            "embedding_version",
            "chunk_index",
            "is_attachment",
            "attachment_id",
            name="uq_chunks_page_ver_idx_attach",
        ),
    )
    op.create_index("idx_chunks_page", "chunks", ["page_id"])
    op.create_index("idx_chunks_qdrant", "chunks", ["qdrant_point_id"])
    op.create_index("idx_chunks_kb_status", "chunks", ["kb_status"])

    # 6) llm_usage
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("page_id", sa.BigInteger, sa.ForeignKey("pages.id")),
        sa.Column("attachment_id", sa.BigInteger, sa.ForeignKey("attachments.id")),
        sa.Column("job_id", sa.BigInteger, sa.ForeignKey("crawl_jobs.id")),
        sa.Column("purpose", sa.Text, nullable=False),  # refine | embedding
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=False),
        sa.Column("completion_tokens", sa.Integer, nullable=False),
        sa.Column("total_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_llm_usage_job", "llm_usage", ["job_id"])


def downgrade() -> None:
    # 역순으로 삭제 (인덱스는 명시 drop — alembic 가시성 위해)
    op.drop_index("idx_llm_usage_job", table_name="llm_usage")
    op.drop_table("llm_usage")

    op.drop_index("idx_chunks_kb_status", table_name="chunks")
    op.drop_index("idx_chunks_qdrant", table_name="chunks")
    op.drop_index("idx_chunks_page", table_name="chunks")
    op.drop_table("chunks")

    op.drop_index("idx_attachments_page", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index("idx_pages_domain", table_name="pages")
    op.drop_index("idx_pages_status", table_name="pages")
    op.drop_table("pages")

    op.drop_index("idx_jobs_domain", table_name="crawl_jobs")
    op.drop_index("idx_jobs_status", table_name="crawl_jobs")
    op.drop_table("crawl_jobs")

    op.drop_table("domains")
