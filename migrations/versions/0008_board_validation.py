"""Board source validation failure evidence.
Revision ID: 0008; Revises: 0007.
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("board_source", sa.Column("validation_error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("board_source", "validation_error")
