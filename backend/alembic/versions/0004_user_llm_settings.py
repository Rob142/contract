"""user llm settings (llm_models list and litellm configuration)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("commercial_llm_model", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("commercial_llm_api_key", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("commercial_llm_api_base", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("local_llm_model", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("local_llm_api_base", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("local_llm_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "local_llm_api_key")
    op.drop_column("users", "local_llm_api_base")
    op.drop_column("users", "local_llm_model")
    op.drop_column("users", "commercial_llm_api_base")
    op.drop_column("users", "commercial_llm_api_key")
    op.drop_column("users", "commercial_llm_model")
