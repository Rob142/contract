"""청구 계산과 인보이스 조회 (설계서 6장).

- 금액은 Decimal로만 계산하고 원 단위로 반올림한다(ROUND_HALF_UP). 클라이언트 합계는 믿지 않는다.
- 고정금액 계약은 지급 단계(선금·잔금 등)를 기준으로 청구한다. 완료율로 금액을 나누지 않는다.
- 시간제는 확인된 시간 × 단가. 추가 작업은 사용자가 합의 사실을 확인한 항목만.
- 중복·초과 청구는 발행 시 지급 단계 행을 잠그고 검사한다. DB 트리거가 한 번 더 막는다.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.errors import AppError, conflict, not_found
from app.db.models import (
    BillingAllocation,
    Client,
    ClientDelivery,
    ClientDeliveryVersion,
    ClientReviewEvent,
    Contract,
    ContractVersion,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentTerm,
    Project,
    Task,
    User,
)
from app.schemas.invoices import (
    BillingCandidates,
    InvoiceDetail,
    InvoiceIn,
    InvoiceItemOut,
    InvoiceSummary,
    PaymentOut,
    TaskCandidate,
    TermCandidate,
)
from app.services.lineage import TERM_LINEAGE_CTE

WON = Decimal(1)


def to_won(value: Decimal) -> Decimal:
    return value.quantize(WON, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- 배분 합계
def allocated_by_term(
    db: Session, term_ids: Sequence[UUID], statuses: tuple[str, ...]
) -> dict[UUID, Decimal]:
    """단계별 배분 합계. 옛 계약에서 이어진 청구도 더한다."""
    if not term_ids:
        return {}
    rows = db.execute(
        text(
            TERM_LINEAGE_CTE  # noqa: S608 - 상수 조각만 이어 붙인다
            + """
            SELECT l.root_id, sum(ba.amount)
              FROM lineage l
              JOIN billing_allocations ba ON ba.payment_term_id = l.term_id
              JOIN invoice_items ii ON ii.id = ba.invoice_item_id
              JOIN invoices i ON i.id = ii.invoice_id
             WHERE i.status = ANY(:statuses)
             GROUP BY l.root_id
            """
        ),
        {"ids": list(term_ids), "statuses": list(statuses)},
    ).all()
    return {term_id: total for term_id, total in rows}


def carried_by_term(db: Session, term_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
    """옛 계약에서 이어진(이월된) 발행 청구액만"""
    if not term_ids:
        return {}
    rows = db.execute(
        text(
            TERM_LINEAGE_CTE  # noqa: S608 - 상수 조각만 이어 붙인다
            + """
            SELECT l.root_id, sum(ba.amount)
              FROM lineage l
              JOIN billing_allocations ba ON ba.payment_term_id = l.term_id
              JOIN invoice_items ii ON ii.id = ba.invoice_item_id
              JOIN invoices i ON i.id = ii.invoice_id
             WHERE i.status = 'issued' AND l.term_id <> l.root_id
             GROUP BY l.root_id
            """
        ),
        {"ids": list(term_ids)},
    ).all()
    return {term_id: total for term_id, total in rows}


def current_successor(db: Session, term_id: UUID, current_version_id: UUID | None) -> UUID | None:
    """옛 단계를 승계를 따라 현재 계약 버전의 단계로 바꾼다. 이어진 곳이 없으면 None."""
    seen: set[UUID] = set()
    tid: UUID | None = term_id
    while tid is not None and tid not in seen:
        seen.add(tid)
        version = db.execute(
            select(PaymentTerm.contract_version_id).where(PaymentTerm.id == tid)
        ).scalar_one_or_none()
        if version is not None and version == current_version_id:
            return tid
        tid = db.execute(
            text("SELECT successor_term_id FROM payment_term_successions WHERE predecessor_term_id = :t"),
            {"t": tid},
        ).scalar_one_or_none()
    return None


def allocated_by_task(db: Session, task_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(BillingAllocation.task_id, func.sum(BillingAllocation.amount))
        .join(InvoiceItem, InvoiceItem.id == BillingAllocation.invoice_item_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(BillingAllocation.task_id.in_(task_ids), Invoice.status == "issued")
        .group_by(BillingAllocation.task_id)
    ).all()
    return {task_id: total for task_id, total in rows}


def project_terms(db: Session, project: Project, *, lock: bool = False) -> list[PaymentTerm]:
    if project.contract_version_id is None:
        return []
    stmt = (
        select(PaymentTerm)
        .where(PaymentTerm.contract_version_id == project.contract_version_id)
        .order_by(PaymentTerm.seq)
    )
    if lock:
        stmt = stmt.with_for_update()
    return list(db.execute(stmt).scalars())


def billing_candidates(db: Session, project: Project) -> BillingCandidates:
    terms = project_terms(db, project)
    issued = allocated_by_term(db, [t.id for t in terms], ("issued",))
    drafted = allocated_by_term(db, [t.id for t in terms], ("draft",))
    carried = carried_by_term(db, [t.id for t in terms])
    tasks = list(
        db.execute(
            select(Task).where(Task.project_id == project.id).order_by(Task.status.desc(), Task.position)
        ).scalars()
    )
    task_billed = allocated_by_task(db, [t.id for t in tasks])
    zero = Decimal(0)
    return BillingCandidates(
        project_id=project.id,
        contract_version_id=project.contract_version_id,
        payment_terms=[
            TermCandidate(
                payment_term_id=t.id,
                seq=t.seq,
                stage=t.stage,
                label=t.label,
                amount=t.amount,
                requirement=t.requirement,
                billed_amount=issued.get(t.id, zero),
                drafted_amount=drafted.get(t.id, zero),
                carried_amount=carried.get(t.id, zero),
                remaining_amount=max(t.amount - issued.get(t.id, zero), zero),
            )
            for t in terms
        ],
        tasks=[
            TaskCandidate(
                task_id=t.id,
                title=t.title,
                status=t.status,
                completed_at=t.completed_at,
                hours=t.hours,
                hourly_rate=t.hourly_rate,
                billed_amount=task_billed.get(t.id, zero),
            )
            for t in tasks
        ],
    )


# ---------------------------------------------------------------- 초안 항목 만들기
def build_items(db: Session, project: Project, body: InvoiceIn) -> tuple[list[InvoiceItem], Decimal]:
    """요청 항목을 검증하고 서버에서 금액을 다시 계산한다."""
    terms = {t.id: t for t in project_terms(db, project)}
    task_ids = {i.task_id for i in body.items if i.task_id}
    tasks = (
        {
            t.id: t
            for t in db.execute(
                select(Task).where(Task.id.in_(task_ids), Task.project_id == project.id)
            ).scalars()
        }
        if task_ids
        else {}
    )
    now = now_utc()
    items: list[InvoiceItem] = []
    for position, item in enumerate(body.items):
        if item.approval_version_id:
            approval_evidence(db, project.id, item.approval_version_id, current=True)
        quantity = item.quantity
        unit_price = item.unit_price
        allocations: list[BillingAllocation] = []

        if item.kind == "payment_stage":
            term = terms.get(item.payment_term_id)  # type: ignore[arg-type]
            if term is None:
                raise AppError(
                    422, "invalid_payment_term", "the payment term does not belong to this project"
                )
            allocations.append(BillingAllocation(payment_term_id=term.id, amount=unit_price))
        elif item.kind in ("task", "hourly"):
            task = tasks.get(item.task_id)  # type: ignore[arg-type]
            if task is None:
                raise AppError(422, "invalid_task", "the task does not belong to this project")
            if item.kind == "hourly":
                # 시간제: 확인된 작업 시간과 단가로만 계산한다
                if task.hours is None or task.hourly_rate is None:
                    raise AppError(
                        422, "task_hours_missing", "record confirmed hours and rate on the task first"
                    )
                quantity, unit_price = task.hours, task.hourly_rate

        amount = to_won(quantity * unit_price)
        if item.kind in ("task", "hourly"):
            allocations.append(BillingAllocation(task_id=item.task_id, amount=amount))

        items.append(
            InvoiceItem(
                position=position,
                kind=item.kind,
                description=item.description.strip(),
                detail=(item.detail or "").strip() or None,
                quantity=quantity,
                unit_price=unit_price,
                amount=amount,
                basis_note=(item.basis_note or "").strip() or None,
                basis_confirmed_at=now if item.basis_confirmed else None,
                approval_version_id=item.approval_version_id,
                allocations=allocations,
            )
        )

    subtotal = sum((i.amount for i in items), Decimal(0))
    total = subtotal + body.tax_amount - body.withholding_amount
    if total < 0:
        raise AppError(422, "negative_total", "withholding cannot exceed the subtotal plus tax")
    return items, subtotal


# ---------------------------------------------------------------- 발행 검증
def check_issuable(db: Session, invoice: Invoice, project: Project) -> None:
    """발행 직전 검사. 지급 단계 행을 잠가 동시 발행을 직렬화한다."""
    if invoice.due_date is None:
        raise AppError(422, "due_date_required", "set a payment due date before issuing")
    terms = {t.id: t for t in project_terms(db, project, lock=True)}
    issued = allocated_by_term(db, list(terms), ("issued",))

    requested: dict[UUID, Decimal] = {}
    for item in invoice.items:
        if item.approval_version_id:
            approval_evidence(db, project.id, item.approval_version_id, current=True)
        for alloc in item.allocations:
            if alloc.payment_term_id:
                requested[alloc.payment_term_id] = (
                    requested.get(alloc.payment_term_id, Decimal(0)) + alloc.amount
                )
        if item.kind == "payment_stage":
            term = terms.get(item.allocations[0].payment_term_id) if item.allocations else None  # type: ignore[arg-type]
            # 지급 요건(예: 검수 완료 후)이 있는 단계는 사용자가 충족을 확인해야 발행할 수 있다
            if term and term.requirement and item.basis_confirmed_at is None:
                raise AppError(
                    422,
                    "requirement_unconfirmed",
                    "confirm the payment requirement before issuing",
                    {"payment_term": term.label, "requirement": term.requirement},
                )

    stale = [tid for tid in requested if tid not in terms]
    if stale:
        raise conflict(
            "stale_payment_term",
            "this draft points to a payment stage of a previous contract; edit the draft",
        )
    over = [
        {
            "payment_term": terms[tid].label,
            "limit": str(terms[tid].amount),
            "already_billed": str(issued.get(tid, Decimal(0))),
            "requested": str(amount),
        }
        for tid, amount in requested.items()
        if issued.get(tid, Decimal(0)) + amount > terms[tid].amount
    ]
    if over:
        raise conflict("over_billed", "this would bill a payment stage beyond its amount", over)


def next_invoice_no(db: Session, owner_id: UUID, year: int) -> str:
    """사용자별 연도 일련번호 (INV-2026-011). 사용자 행을 잠가 동시 발행에도 겹치지 않게 한다."""
    db.execute(select(User.id).where(User.id == owner_id).with_for_update())
    prefix = f"INV-{year}-"
    last = db.execute(
        select(func.max(func.substr(Invoice.invoice_no, len(prefix) + 1))).where(
            Invoice.owner_id == owner_id, Invoice.invoice_no.like(f"{prefix}%")
        )
    ).scalar_one()
    return f"{prefix}{(int(last) if last and last.isdigit() else 0) + 1:03d}"


def build_snapshot(db: Session, invoice: Invoice, project: Project, user: User) -> dict[str, Any]:
    """발행 시점의 거래처·발행자·조건·항목을 고정한다. 이후 원본이 바뀌어도 문서는 그대로다."""
    client = db.get(Client, project.client_id)
    contract: dict[str, Any] | None = None
    if project.contract_version_id:
        version = db.get(ContractVersion, project.contract_version_id)
        contract_row = db.get(Contract, version.contract_id) if version else None
        if version and contract_row:
            contract = {"title": contract_row.title, "version_no": version.version_no}
    terms = {t.id: t for t in project_terms(db, project)}
    return {
        "issuer": {
            "name": user.issuer_name or user.name,
            "display_name": user.issuer_display_name,
            "contact": user.issuer_contact or user.email,
            "bank_name": user.bank_name,
            "bank_account": user.bank_account,
        },
        "client": {
            "name": client.name if client else "",
            "contact_name": client.contact_name if client else None,
            "contact_email": client.contact_email if client else None,
        },
        "project": {"id": str(project.id), "name": project.name},
        "contract": contract,
        "items": [
            {
                "description": i.description,
                "detail": i.detail,
                "kind": i.kind,
                "quantity": str(i.quantity),
                "unit_price": str(i.unit_price),
                "amount": str(i.amount),
                "approval_evidence": approval_evidence(db, project.id, i.approval_version_id)
                if i.approval_version_id
                else None,
                "basis_note": i.basis_note,
                "basis_confirmed_at": i.basis_confirmed_at.isoformat() if i.basis_confirmed_at else None,
                "payment_term": (
                    {
                        "label": terms[a.payment_term_id].label,
                        "requirement": terms[a.payment_term_id].requirement,
                    }
                    if (a := next((x for x in i.allocations if x.payment_term_id), None))
                    and a.payment_term_id in terms
                    else None
                ),
            }
            for i in invoice.items
        ],
        "subtotal": str(invoice.subtotal),
        "tax_amount": str(invoice.tax_amount),
        "withholding_amount": str(invoice.withholding_amount),
        "adjustment_note": invoice.adjustment_note,
        "total": str(invoice.total),
        "currency": invoice.currency,
    }


# ---------------------------------------------------------------- 조회
SUMMARY_SQL = """
SELECT i.id, i.invoice_no, i.title, i.status, i.project_id, p.name AS project_name,
       COALESCE(i.snapshot->'client'->>'name', c.name) AS client_name,
       i.total, b.paid_amount, b.balance, b.payment_status, b.is_overdue,
       i.issue_date, i.due_date, i.created_at
  FROM invoices i
  JOIN v_invoice_balances b ON b.invoice_id = i.id
  JOIN projects p ON p.id = i.project_id
  JOIN clients c ON c.id = p.client_id
 WHERE i.owner_id = :owner
"""


def summary_rows(
    db: Session, owner_id: UUID, where: str = "", params: dict[str, Any] | None = None
) -> list[Any]:
    sql = SUMMARY_SQL + where + " ORDER BY COALESCE(i.issue_date, i.created_at::date) DESC, i.created_at DESC"
    return list(db.execute(text(sql), {"owner": owner_id, **(params or {})}).mappings())


def to_summary(row: Any) -> InvoiceSummary:
    return InvoiceSummary(
        id=row["id"],
        invoice_no=row["invoice_no"],
        title=row["title"],
        status=row["status"],
        project_id=row["project_id"],
        project_name=row["project_name"],
        client_name=row["client_name"],
        total=row["total"],
        paid_amount=row["paid_amount"],
        balance=row["balance"] if row["status"] == "issued" else Decimal(0),
        payment_status=row["payment_status"],
        is_overdue=bool(row["is_overdue"]),
        issue_date=row["issue_date"],
        due_date=row["due_date"],
        created_at=row["created_at"],
    )


def get_owned_invoice(db: Session, owner_id: UUID, invoice_id: UUID, *, lock: bool = False) -> Invoice:
    stmt = select(Invoice).where(Invoice.id == invoice_id, Invoice.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    invoice = db.execute(stmt).scalar_one_or_none()
    if invoice is None:
        raise not_found("invoice")
    return invoice


def build_detail(db: Session, owner_id: UUID, invoice_id: UUID) -> InvoiceDetail:
    invoice = get_owned_invoice(db, owner_id, invoice_id)
    rows = summary_rows(db, owner_id, " AND i.id = :id", {"id": invoice_id})
    summary = to_summary(rows[0])
    payments = list(
        db.execute(
            select(Payment).where(Payment.invoice_id == invoice.id).order_by(Payment.created_at)
        ).scalars()
    )
    replaced_by = db.execute(
        select(Invoice.id).where(Invoice.replaces_invoice_id == invoice.id).limit(1)
    ).scalar_one_or_none()
    return InvoiceDetail(
        **summary.model_dump(),
        subtotal=invoice.subtotal,
        tax_amount=invoice.tax_amount,
        withholding_amount=invoice.withholding_amount,
        adjustment_note=invoice.adjustment_note,
        items=[
            InvoiceItemOut(
                id=i.id,
                position=i.position,
                kind=i.kind,  # type: ignore[arg-type]
                description=i.description,
                detail=i.detail,
                quantity=i.quantity,
                unit_price=i.unit_price,
                amount=i.amount,
                payment_term_id=next((a.payment_term_id for a in i.allocations if a.payment_term_id), None),
                task_id=next((a.task_id for a in i.allocations if a.task_id), None),
                basis_note=i.basis_note,
                basis_confirmed_at=i.basis_confirmed_at,
                approval_version_id=i.approval_version_id,
            )
            for i in invoice.items
        ],
        payments=[PaymentOut.model_validate(p) for p in payments],
        snapshot=invoice.snapshot,
        replaces_invoice_id=invoice.replaces_invoice_id,
        replaced_by_invoice_id=replaced_by,
        cancelled_at=invoice.cancelled_at,
        cancel_reason=invoice.cancel_reason,
        version=invoice.updated_at,
    )


def approval_evidence(
    db: Session, project_id: UUID, version_id: UUID, current: bool = False
) -> dict[str, Any]:
    row = db.execute(
        select(ClientDeliveryVersion, ClientDelivery, ClientReviewEvent)
        .join(ClientDelivery, ClientDelivery.id == ClientDeliveryVersion.delivery_id)
        .join(ClientReviewEvent, ClientReviewEvent.version_id == ClientDeliveryVersion.id)
        .where(
            ClientDeliveryVersion.id == version_id,
            ClientDelivery.project_id == project_id,
            ClientReviewEvent.kind == "approved",
        )
    ).first()
    if row is None:
        raise AppError(422, "approval_required", "이 프로젝트의 승인된 결과물 버전을 선택하세요")
    version, delivery, event = row
    if current:
        latest = db.scalar(
            select(func.max(ClientDeliveryVersion.seq)).where(
                ClientDeliveryVersion.delivery_id == delivery.id
            )
        )
        if version.seq != latest:
            raise AppError(422, "approval_outdated", "새 버전이 제출되었습니다. 최신 승인 기록을 확인하세요")
    return dict(
        version_id=str(version.id),
        title=delivery.title,
        seq=version.seq,
        actor=event.actor_name,
        workspace=event.workspace_name,
        approved_at=event.created_at.isoformat(),
    )
