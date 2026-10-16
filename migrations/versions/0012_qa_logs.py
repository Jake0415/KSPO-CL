"""Create missing QA log table, leaving collected data untouched."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    if "qa_logs" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "qa_logs",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text()),
            sa.Column("sources", postgresql.JSONB()),
            sa.Column("is_answered", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("error_message", sa.Text()),
            sa.Column("satisfaction", sa.Integer()),
            sa.Column("latency_ms", sa.Integer()),
            sa.Column("provider", sa.Text()),
            sa.Column("model", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade():
    op.drop_table("qa_logs")
