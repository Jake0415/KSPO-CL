"""kpi_snapshots — 일별 KPI 4종 누적 테이블

Revision ID: 0005_kpi_snapshots
Revises: 0004_stats_views
Create Date: 2026-05-08

매일 00:30 KST cron이 (전체 1행 + 활성 도메인별 N행) snapshot을 INSERT.
M5.T5.4 — 파일럿 보고서 + Admin 대시보드 차트 데이터 소스.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_kpi_snapshots"
down_revision = "0004_stats_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "measured_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # NULL = 전체 도메인 합산
        sa.Column(
            "domain_id",
            sa.BigInteger,
            sa.ForeignKey("domains.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("coverage_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("avg_freshness_days", sa.Numeric(8, 2), nullable=True),
        sa.Column("job_success_rate_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("monthly_cost_krw", sa.Numeric(12, 2), nullable=False),
        sa.Column("indexed_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("dropped_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("error_count", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_index("idx_kpi_snapshots_measured_at", "kpi_snapshots", ["measured_at"])
    op.create_index("idx_kpi_snapshots_domain", "kpi_snapshots", ["domain_id"])


def downgrade() -> None:
    op.drop_index("idx_kpi_snapshots_domain", table_name="kpi_snapshots")
    op.drop_index("idx_kpi_snapshots_measured_at", table_name="kpi_snapshots")
    op.drop_table("kpi_snapshots")
