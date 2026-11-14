"""portfolio items, assets and feedback quotes

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((SQL_DIR / "07_portfolio.sql").read_text(encoding="utf-8"))
    finally:
        cursor.close()


def downgrade() -> None:
    for table in ("portfolio_quotes", "portfolio_assets", "portfolio_items"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
