"""progress sharing: attachments, share links, feedback, view log, revision counter

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-14
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute((SQL_DIR / "06_progress_share.sql").read_text(encoding="utf-8"))
    finally:
        cursor.close()


def downgrade() -> None:
    for table in ("extra_quotes", "revision_requests", "view_events", "task_feedback", "share_links"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS forbid_update()")
    # attachments는 0001 모양(파일 전용)으로 되돌린다. 링크 첨부는 지운다
    op.execute("DELETE FROM attachments WHERE file_id IS NULL")
    op.execute("DROP TRIGGER IF EXISTS attachments_set_updated_at ON attachments")
    for column in (
        "owner_id",
        "invoice_id",
        "kind",
        "doc_type",
        "title",
        "url",
        "issued_on",
        "amount",
        "memo",
        "updated_at",
    ):
        op.execute(f"ALTER TABLE attachments DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE attachments ALTER COLUMN file_id SET NOT NULL")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS included_revisions")
    op.execute("UPDATE tasks SET source = 'manual' WHERE source = 'template'")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_source_check")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_source_check "
        "CHECK (source IN ('contract', 'estimated', 'manual'))"
    )
