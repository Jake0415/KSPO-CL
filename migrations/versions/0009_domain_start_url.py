"""Add optional crawl entry URL without changing collected data."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("domains", sa.Column("start_url", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("domains", "start_url")
