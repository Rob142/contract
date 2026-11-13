"""initial schema: tables, billing rules, views

Revision ID: 0001
Revises:
Create Date: 2026-11-12
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SQL_FILES = ["01_schema.sql", "02_billing_rules.sql", "03_views.sql"]


def _execute_script(sql: str) -> None:
    # 원시 드라이버 커서로 실행: 여러 문장·$$ 블록·% 문자를 그대로 보낸다
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    for name in SQL_FILES:
        _execute_script((SQL_DIR / name).read_text(encoding="utf-8"))


def downgrade() -> None:
    _execute_script(
        """
        DROP VIEW IF EXISTS v_contract_latest, v_project_summary, v_invoice_balances;
        DROP TABLE IF EXISTS
          generated_documents, payments, billing_allocations, invoice_items, invoices,
          revision_prompts, analysis_results, analysis_jobs,
          attachments, task_checklist_items, tasks, projects,
          payment_terms, contract_fields, contract_text_blocks, contract_text_versions,
          contract_pages, contract_versions, contracts,
          idempotency_keys, audit_events, files, clients, user_sessions, users
          CASCADE;
        DROP FUNCTION IF EXISTS
          set_updated_at(), invoices_guard_update(), invoices_guard_delete(),
          invoice_children_guard(), invoices_check_on_issue(), payments_guard_insert(),
          payments_guard_update(), payments_guard_delete(), payments_invalidate_documents();
        """
    )
