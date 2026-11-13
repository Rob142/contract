"""make account deletion possible without loosening per-row protections

1) contract_fields.confirmed_by, contract_text_versions.edited_by: SET NULL → CASCADE
   SET NULL이 "확정된 항목은 확인자가 있어야 한다" CHECK와 충돌해 사용자 삭제가 실패했다.
   이 행들은 같은 사용자의 계약서에 속하므로 사용자와 함께 지운다.

2) ON DELETE RESTRICT → NO ACTION DEFERRABLE INITIALLY DEFERRED
   RESTRICT(즉시 검사)와 NO ACTION(문장 끝 검사)은 사용자 삭제의 연쇄 삭제 도중
   (파일이 버전보다 먼저 지워지는 순간) 실패했다. PostgreSQL의 연쇄 삭제는 내부 트리거로
   돌기 때문이다. 커밋 시점 검사로 바꾸면 참조 중인 행의 단독 삭제는 여전히 거절되고,
   계정 전체를 지울 때만 통과한다. 입금 기록은 삭제 금지 트리거가 계속 지킨다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESTRICT_FKS = [
    ("analysis_jobs", "analysis_jobs_text_version_id_fkey"),
    ("attachments", "attachments_file_id_fkey"),
    ("billing_allocations", "billing_allocations_payment_term_id_fkey"),
    ("billing_allocations", "billing_allocations_task_id_fkey"),
    ("contract_text_versions", "contract_text_versions_based_on_id_fkey"),
    ("contract_versions", "contract_versions_file_id_owner_id_fkey"),
    ("contracts", "contracts_client_id_owner_id_fkey"),
    ("generated_documents", "generated_documents_file_id_owner_id_fkey"),
    ("generated_documents", "generated_documents_invoice_id_fkey"),
    ("generated_documents", "generated_documents_payment_id_fkey"),
    ("invoices", "invoices_project_id_owner_id_fkey"),
    ("invoices", "invoices_replaces_invoice_id_fkey"),
    ("payments", "payments_invoice_id_fkey"),
    ("payments", "payments_recorded_by_fkey"),
    ("projects", "projects_client_id_owner_id_fkey"),
    ("projects", "projects_contract_version_id_owner_id_fkey"),
]


def _replace_user_fk(table: str, column: str, on_delete: str) -> None:
    name = f"{table}_{column}_fkey"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=on_delete)


def _set_delete_action(table: str, constraint: str, action: str) -> None:
    """제약 정의를 그대로 두고 ON DELETE 동작만 바꾼다."""
    # table·constraint·action은 이 파일 안의 상수만 들어온다 (외부 입력 아님)
    sql = f"""
        DO $$
        DECLARE def text;
        BEGIN
          SELECT pg_get_constraintdef(oid) INTO def FROM pg_constraint WHERE conname = '{constraint}';
          def := regexp_replace(def, ' ON DELETE (RESTRICT|NO ACTION|CASCADE|SET NULL)', '');
          def := regexp_replace(def, ' (NOT )?DEFERRABLE( INITIALLY (DEFERRED|IMMEDIATE))?', '');
          EXECUTE format(
            'ALTER TABLE {table} DROP CONSTRAINT {constraint}, ADD CONSTRAINT {constraint} %s {action}',
            def);
        END $$;
        """  # noqa: S608
    op.execute(sql)


def upgrade() -> None:
    _replace_user_fk("contract_fields", "confirmed_by", "CASCADE")
    _replace_user_fk("contract_text_versions", "edited_by", "CASCADE")
    for table, constraint in RESTRICT_FKS:
        _set_delete_action(table, constraint, "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED")


def downgrade() -> None:
    for table, constraint in RESTRICT_FKS:
        _set_delete_action(table, constraint, "ON DELETE RESTRICT")
    _replace_user_fk("contract_fields", "confirmed_by", "SET NULL")
    _replace_user_fk("contract_text_versions", "edited_by", "SET NULL")
