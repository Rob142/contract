"""contract revision after billing: payment term successions

청구한 뒤 수정 계약서를 반영할 때 발행 기록은 그대로 두고
옛 지급 단계 → 새 지급 단계 승계를 기록한다. 단계 한도는 계보 전체 청구액으로 검사한다.
(계약_변경_반영_설계.md)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _execute_script(sql: str) -> None:
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def upgrade() -> None:
    _execute_script((SQL_DIR / "05_contract_revision.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    # 발행 검사를 0001 판으로 되돌린다
    original = (SQL_DIR / "02_billing_rules.sql").read_text(encoding="utf-8")
    start = original.index("CREATE OR REPLACE FUNCTION invoices_check_on_issue()")
    end = original.index("CREATE TRIGGER invoices_check_on_issue")
    _execute_script(
        """
        DROP TRIGGER IF EXISTS billing_allocations_current_term ON billing_allocations;
        DROP FUNCTION IF EXISTS billing_allocations_current_term();
        DROP TABLE IF EXISTS payment_term_successions;
        DROP FUNCTION IF EXISTS payment_term_successions_guard();
        """
        + original[start:end]
        + "DROP FUNCTION IF EXISTS term_billed_total(uuid, text[]);"
    )
