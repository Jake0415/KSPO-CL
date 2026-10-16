"""doc_quality table — 문서 품질 평가 + Quadrant 자동 분류.

Revision ID: 0006
Revises: 0005_kpi_snapshots
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005_kpi_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_quality",
        sa.Column("page_id", sa.BigInteger, sa.ForeignKey("pages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("quality_score", sa.Numeric(4, 3), server_default="0", nullable=False),
        sa.Column("structure_score", sa.Numeric(4, 3), server_default="0", nullable=False),
        sa.Column("freshness_score", sa.Numeric(4, 3), server_default="0", nullable=False),
        sa.Column("trust_score", sa.Numeric(4, 3), server_default="1.0", nullable=False),
        sa.Column("importance_score", sa.Numeric(4, 3), server_default="0", nullable=False),
        sa.Column("duplicate_score", sa.Numeric(4, 3), server_default="1.0", nullable=False),
        sa.Column("quadrant", sa.Text, server_default="Q2", nullable=False),
        sa.Column("extraction_method", sa.Text, nullable=True),
        sa.Column("body_length", sa.Integer, server_default="0", nullable=False),
        sa.Column("korean_ratio", sa.Numeric(4, 3), server_default="0", nullable=False),
        sa.Column("has_title", sa.Boolean, server_default="false", nullable=False),
        sa.Column("has_posted_at", sa.Boolean, server_default="false", nullable=False),
        sa.Column("has_summary", sa.Boolean, server_default="false", nullable=False),
        sa.Column("keyword_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("scorer_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("scored_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_doc_quality_quadrant", "doc_quality", ["quadrant"])
    op.create_index("ix_doc_quality_quality_score", "doc_quality", ["quality_score"])


def downgrade() -> None:
    op.drop_index("ix_doc_quality_quality_score")
    op.drop_index("ix_doc_quality_quadrant")
    op.drop_table("doc_quality")
