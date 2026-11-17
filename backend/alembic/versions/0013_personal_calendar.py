"""Keep account-private calendar entries separate from project work."""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE personal_calendar_events (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      owner_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
      title text NOT NULL, notes text NOT NULL DEFAULT '', scheduled_on date NOT NULL,
      is_done boolean NOT NULL DEFAULT false, archived_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX personal_calendar_owner_date ON personal_calendar_events(owner_id,scheduled_on)
      WHERE archived_at IS NULL;
    """)


def downgrade() -> None:
    raise RuntimeError("Personal schedules must be preserved before downgrade")
