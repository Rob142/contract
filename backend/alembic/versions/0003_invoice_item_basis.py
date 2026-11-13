"""invoice item billing basis (user-confirmed requirement)

지급 요건(예: 검수 완료 후 잔금)은 외부 업체가 시스템에 들어오지 않으므로
프리랜서가 확인한 사실을 직접 기록한다 (설계서 1장). 청구 항목마다 확인 내용과 시각을 남긴다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoice_items", sa.Column("basis_note", sa.Text(), nullable=True))
    op.add_column(
        "invoice_items", sa.Column("basis_confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("invoice_items", "basis_confirmed_at")
    op.drop_column("invoice_items", "basis_note")
