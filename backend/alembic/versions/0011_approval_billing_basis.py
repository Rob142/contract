"""Link a manually selected approved delivery version to an invoice item."""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE invoice_items ADD COLUMN approval_version_id uuid "
        "REFERENCES client_delivery_versions(id)"
    )


def downgrade() -> None:
    raise RuntimeError("Approval evidence must be preserved")
