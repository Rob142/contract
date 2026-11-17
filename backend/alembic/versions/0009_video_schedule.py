"""Add video project draft delivery details.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("draft_delivery_date", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("draft_delivery_exempt", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "draft_delivery_exempt")
    op.drop_column("projects", "draft_delivery_date")
