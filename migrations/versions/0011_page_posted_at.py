"""Add missing publication date without changing existing collected data."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("pages")}
    if "posted_at" not in columns:
        op.add_column("pages", sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("pages", "posted_at")
