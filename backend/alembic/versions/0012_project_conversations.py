"""Persistent requests and mutually accepted real-time conversation sessions."""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE project_chat_sessions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id uuid NOT NULL REFERENCES projects ON DELETE CASCADE,
      requested_by uuid NOT NULL REFERENCES users,
      responded_by uuid REFERENCES users,
      topic text NOT NULL,
      state text NOT NULL CHECK(state IN ('pending','active','closed','declined','expired')),
      expires_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX one_open_project_chat ON project_chat_sessions(project_id)
      WHERE state IN ('pending','active');
    CREATE TABLE project_messages (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id uuid NOT NULL REFERENCES projects ON DELETE CASCADE,
      session_id uuid REFERENCES project_chat_sessions,
      actor_id uuid NOT NULL REFERENCES users,
      actor_name text NOT NULL,
      actor_side text NOT NULL CHECK(actor_side IN ('client','freelancer')),
      body text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX project_messages_timeline ON project_messages(project_id,created_at);
    """)


def downgrade() -> None:
    raise RuntimeError("Conversation histories must be preserved")
