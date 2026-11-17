"""Client workspaces, explicit project grants, marketplace and versioned reviews."""

from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((Path(__file__).parent.parent / "sql/09_client_service.sql").read_text())
    finally:
        cursor.close()


def downgrade() -> None:
    raise RuntimeError("Client records must be exported before a destructive downgrade")
