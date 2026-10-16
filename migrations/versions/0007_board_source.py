"""board_source table + pages.board_source_id, drop domains.is_board.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "board_source",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("domain_id", sa.BigInteger, sa.ForeignKey("domains.id", ondelete="CASCADE"), nullable=False),
        sa.Column("list_url", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="candidate", nullable=False),
        sa.Column("newest_first", sa.Boolean, server_default="true", nullable=False),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("domain_id", "list_url", name="uq_board_source_domain_list_url"),
    )
    op.create_index("ix_board_source_status", "board_source", ["status"])
    op.add_column(
        "pages",
        sa.Column("board_source_id", sa.BigInteger, sa.ForeignKey("board_source.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_pages_board_source_id", "pages", ["board_source_id"])

    # 기존 is_board=true 도메인 루트를 candidate board_source로 이관
    # is_board 컬럼이 존재할 때만 실행 (fresh install에서는 해당 컬럼이 없음)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'domains' AND column_name = 'is_board'"
    ))
    if result.fetchone():
        op.execute(
            """
            INSERT INTO board_source (domain_id, list_url, status)
            SELECT id, scheme || '://' || host, 'candidate'
            FROM domains WHERE is_board = true
            ON CONFLICT (domain_id, list_url) DO NOTHING
            """
        )
        op.drop_column("domains", "is_board")


def downgrade() -> None:
    op.add_column("domains", sa.Column("is_board", sa.Boolean, server_default="false", nullable=False))
    op.drop_index("ix_pages_board_source_id", table_name="pages")
    op.drop_column("pages", "board_source_id")
    op.drop_index("ix_board_source_status", table_name="board_source")
    op.drop_table("board_source")
