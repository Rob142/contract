"""프로젝트·작업 조회와 변경. 모든 조회는 owner_id로 범위를 제한한다."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, func, select, text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.errors import conflict, not_found
from app.db.models import Client, ContractVersion, PaymentTerm, Project, Task, v_project_summary
from app.schemas.projects import (
    ClientRef,
    PaymentTermOut,
    ProjectDetail,
    ProjectSummary,
    TaskOut,
)
from app.services.lineage import TERM_LINEAGE_CTE

STATUS_ORDER = case({"active": 0, "completed": 1, "archived": 2}, value=Project.status)


def summary_select(owner_id: UUID) -> Select[Any]:
    s = v_project_summary.c
    return (
        select(
            Project,
            Client.name.label("client_name"),
            s.total_tasks,
            s.done_tasks,
            s.progress_pct,
            s.billed_amount,
            s.paid_amount,
            s.outstanding_amount,
        )
        .join(Client, Client.id == Project.client_id)
        .join(v_project_summary, s.project_id == Project.id)
        .where(Project.owner_id == owner_id)
    )


def to_summary(row: Any) -> ProjectSummary:
    p: Project = row.Project
    return ProjectSummary(
        id=p.id,
        name=p.name,
        job_type=p.job_type,  # type: ignore[arg-type]
        status=p.status,  # type: ignore[arg-type]
        client=ClientRef(id=p.client_id, name=row.client_name),
        start_date=p.start_date,
        due_date=p.due_date,
        contract_amount=p.contract_amount,
        total_tasks=row.total_tasks,
        done_tasks=row.done_tasks,
        progress_pct=int(row.progress_pct) if row.progress_pct is not None else None,
        billed_amount=row.billed_amount,
        paid_amount=row.paid_amount,
        outstanding_amount=row.outstanding_amount,
        has_contract=p.contract_version_id is not None,
        version=p.updated_at,
    )


def list_summaries(
    db: Session, owner_id: UUID, status: str | None, limit: int, offset: int
) -> list[ProjectSummary]:
    stmt = summary_select(owner_id)
    if status:
        stmt = stmt.where(Project.status == status)
    stmt = stmt.order_by(
        STATUS_ORDER, Project.due_date.asc().nulls_last(), Project.created_at.desc(), Project.id
    )
    rows = db.execute(stmt.limit(limit).offset(offset)).all()
    return [to_summary(r) for r in rows]


def count_by_status(db: Session, owner_id: UUID) -> dict[str, int]:
    rows = db.execute(
        select(Project.status, func.count()).where(Project.owner_id == owner_id).group_by(Project.status)
    ).all()
    counts = {"active": 0, "completed": 0, "archived": 0}
    counts.update({status: n for status, n in rows})
    return {"all": sum(counts.values()), **counts}


def term_billing(db: Session, term_ids: Sequence[UUID]) -> dict[UUID, dict[str, Any]]:
    """지급 단계별 청구 현황. 취소된 인보이스는 제외한다."""
    if not term_ids:
        return {}
    rows = db.execute(
        text(
            TERM_LINEAGE_CTE  # noqa: S608 - 상수 조각만 이어 붙인다
            + """
            SELECT l.root_id AS term_id, (l.term_id <> l.root_id) AS carried,
                   i.id AS invoice_id, i.status, b.payment_status, ba.amount, i.created_at
              FROM lineage l
              JOIN billing_allocations ba ON ba.payment_term_id = l.term_id
              JOIN invoice_items ii ON ii.id = ba.invoice_item_id
              JOIN invoices i ON i.id = ii.invoice_id
              JOIN v_invoice_balances b ON b.invoice_id = i.id
             WHERE i.status <> 'cancelled'
             ORDER BY i.created_at
            """
        ),
        {"ids": list(term_ids)},
    ).mappings()
    result: dict[UUID, dict[str, Any]] = {}
    for r in rows:
        info = result.setdefault(
            r["term_id"],
            {"issued": [], "draft": False, "billed": Decimal(0), "carried": Decimal(0), "invoice_id": None},
        )
        info["invoice_id"] = r["invoice_id"]
        if r["status"] == "issued":
            info["issued"].append(r["payment_status"])
            info["billed"] += r["amount"]
            if r["carried"]:
                info["carried"] += r["amount"]
        else:
            info["draft"] = True
    return result


def get_detail(db: Session, owner_id: UUID, project_id: UUID) -> ProjectDetail:
    row = db.execute(summary_select(owner_id).where(Project.id == project_id)).one_or_none()
    if row is None:
        raise not_found("project")
    summary = to_summary(row)
    terms: Sequence[PaymentTerm] = []
    contract_id: UUID | None = None
    if row.Project.contract_version_id:
        contract_id = db.execute(
            select(ContractVersion.contract_id).where(ContractVersion.id == row.Project.contract_version_id)
        ).scalar_one_or_none()
        terms = (
            db.execute(
                select(PaymentTerm)
                .where(PaymentTerm.contract_version_id == row.Project.contract_version_id)
                .order_by(PaymentTerm.seq)
            )
            .scalars()
            .all()
        )
    billing = term_billing(db, [t.id for t in terms])
    out_terms = []
    for t in terms:
        info = billing.get(t.id)
        if info is None:
            status = "unbilled"
        elif info["issued"]:
            status = (
                "paid"
                if all(s == "paid" for s in info["issued"]) and info["billed"] >= t.amount
                else "billed"
            )
        else:
            status = "draft"
        out_terms.append(
            PaymentTermOut.model_validate(t).model_copy(
                update={
                    "billing_status": status,
                    "billed_amount": info["billed"] if info else Decimal(0),
                    "carried_amount": info["carried"] if info else Decimal(0),
                    "invoice_id": info["invoice_id"] if info else None,
                }
            )
        )
    return ProjectDetail(**summary.model_dump(), contract_id=contract_id, payment_terms=out_terms)


def get_owned_project(db: Session, owner_id: UUID, project_id: UUID, *, lock: bool = False) -> Project:
    stmt = select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    project = db.execute(stmt).scalar_one_or_none()
    if project is None:
        raise not_found("project")
    return project


def get_owned_client(db: Session, owner_id: UUID, client_id: UUID) -> Client:
    client = db.execute(
        select(Client).where(Client.id == client_id, Client.owner_id == owner_id)
    ).scalar_one_or_none()
    if client is None:
        raise not_found("client")
    return client


def get_owned_task(db: Session, owner_id: UUID, task_id: UUID) -> Task:
    """작업에는 owner_id가 없으므로 프로젝트와 조인해 소유권을 확인한다."""
    task = db.execute(
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(Task.id == task_id, Project.owner_id == owner_id)
    ).scalar_one_or_none()
    if task is None:
        raise not_found("task")
    return task


def list_tasks(db: Session, project_id: UUID) -> list[TaskOut]:
    tasks = (
        db.execute(
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(
                case({"todo": 0, "doing": 1, "done": 2}, value=Task.status), Task.position, Task.created_at
            )
        )
        .scalars()
        .all()
    )
    return [TaskOut.model_validate(t) for t in tasks]


def next_position(db: Session, project_id: UUID, status: str) -> int:
    current = db.execute(
        select(func.max(Task.position)).where(Task.project_id == project_id, Task.status == status)
    ).scalar_one()
    return 0 if current is None else current + 1


def set_status(task: Task, status: str) -> None:
    if task.status != status:
        task.status = status
        task.completed_at = now_utc() if status == "done" else None


def move_task(db: Session, project: Project, task: Task, status: str, index: int) -> None:
    """대상 열에 끼워 넣고 그 열의 순서를 0부터 다시 매긴다. 호출 전에 프로젝트 행을 잠근다."""
    column = (
        db.execute(
            select(Task)
            .where(Task.project_id == project.id, Task.status == status, Task.id != task.id)
            .order_by(Task.position, Task.created_at)
        )
        .scalars()
        .all()
    )
    ordered = list(column)
    ordered.insert(min(index, len(ordered)), task)
    set_status(task, status)
    for position, item in enumerate(ordered):
        if item.position != position:
            item.position = position


def contract_billing_count(db: Session, version_id: UUID) -> int:
    """이 계약 버전의 지급 단계로 청구한 인보이스 수 (초안·취소 포함).

    하나라도 있으면 연결을 풀거나 바꿀 수 없다. 청구 이력이 지급 단계에 묶여 있어
    떼어 내면 "이미 청구한 단계"를 다시 청구할 수 있게 되기 때문이다.
    """
    term_ids = list(
        db.execute(select(PaymentTerm.id).where(PaymentTerm.contract_version_id == version_id)).scalars()
    )
    if not term_ids:
        return 0
    # 수정 계약으로 이어진 옛 단계의 청구도 센다
    return int(
        db.execute(
            text(
                TERM_LINEAGE_CTE  # noqa: S608 - 상수 조각만 이어 붙인다
                + """
                SELECT count(DISTINCT ii.invoice_id)
                  FROM lineage l
                  JOIN billing_allocations ba ON ba.payment_term_id = l.term_id
                  JOIN invoice_items ii ON ii.id = ba.invoice_item_id
                """
            ),
            {"ids": term_ids},
        ).scalar_one()
    )


def ensure_contract_detachable(db: Session, version_id: UUID) -> None:
    if (count := contract_billing_count(db, version_id)) > 0:
        raise conflict(
            "contract_has_billing",
            "invoices already use this contract's payment terms",
            {"invoice_count": count},
        )
