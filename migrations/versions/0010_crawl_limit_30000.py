"""Raise crawl defaults without touching collected content or vector data."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None
def upgrade():
    op.alter_column("domains", "max_pages", server_default="30000")
    op.execute(sa.text("UPDATE domains SET max_pages = 30000 WHERE max_pages IN (2000, 5000)"))
def downgrade():
    # Preserve site settings: their previous values cannot be inferred safely.
    op.alter_column("domains", "max_pages", server_default="2000")
