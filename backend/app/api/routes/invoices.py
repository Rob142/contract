from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.clock import month_range, now_utc, today
from app.core.errors import AppError, conflict, not_found
from app.core.idempotency import require_idempotency_key, run_idempotent
from app.core.pagination import PageParams, encode_cursor, page_params
from app.core.versioning import assert_version
from app.db.models import BillingAllocation, Invoice, InvoiceItem, Payment, User
from app.db.session import get_db
from app.schemas.invoices import (
    BillingCandidates,
    CancelIn,
    InvoiceCounts,
    InvoiceDetail,
    InvoiceGroup,
    InvoiceIn,
    InvoiceKpis,
    InvoiceList,
    InvoiceUpdate,
    IssueIn,
    PaymentIn,
)
from app.services.documents import ReceiptFacts, invoice_pdf, receipt_pdf
from app.services.invoices import (
    billing_candidates,
    build_detail,
    build_items,
    build_snapshot,
    check_issuable,
    current_successor,
    get_owned_invoice,
    next_invoice_no,
    summary_rows,
    to_summary,
)
from app.services.projects import get_owned_project

router = APIRouter(tags=["invoices"])

GROUP_SQL = {
    "draft": "i.status = 'draft'",
    "unpaid": "i.status = 'issued' AND b.payment_status = 'unpaid'",
    "partial": "i.status = 'issued' AND b.payment_status = 'partial'",
    "paid": "i.status = 'issued' AND b.payment_status = 'paid'",
    "overdue": "b.is_overdue",
    # 대시보드·목록 KPI "미수액"과 같은 기준: 발행했고 잔액이 남은 것
    "outstanding": "i.status = 'issued' AND b.balance > 0",
    "cancelled": "i.status = 'cancelled'",
}


def _pdf_response(content: bytes, filename: str, download: bool) -> Response:
    disposition = "attachment" if download else "inline"
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---------------------------------------------------------------- 청구 후보
@router.get("/projects/{project_id}/billing-candidates", response_model=BillingCandidates)
def read_candidates(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> BillingCandidates:
    return billing_candidates(db, get_owned_project(db, user.id, project_id))


# ---------------------------------------------------------------- 목록
@router.get("/invoices", response_model=InvoiceList)
def list_invoices(
    group: InvoiceGroup | None = Query(default=None),
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    project_id: UUID | None = Query(default=None),
    page: PageParams = Depends(page_params),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceList:
    # 아래 SQL 조각은 이 파일의 상수만 이어 붙인다. 사용자 값은 모두 바인드 파라미터로 넘긴다
    filters, params = "", dict[str, Any]()
    if month:
        start, end = month_range(date.fromisoformat(f"{month}-01"))
        filters += (
            " AND COALESCE(i.issue_date, i.created_at::date) >= :m_start"
            " AND COALESCE(i.issue_date, i.created_at::date) < :m_end"
        )
        params.update(m_start=start, m_end=end)
    if project_id:
        filters += " AND i.project_id = :project_id"
        params["project_id"] = project_id

    # 탭 숫자: 기간·프로젝트 필터는 반영하고 상태 탭은 반영하지 않는다
    counts_row = (
        db.execute(
            text(
                "SELECT count(*) AS all, "  # noqa: S608 - 상수 조각만 이어 붙인다
                + ", ".join(f"count(*) FILTER (WHERE {cond}) AS {name}" for name, cond in GROUP_SQL.items())
                + " FROM invoices i JOIN v_invoice_balances b ON b.invoice_id = i.id"
                + " WHERE i.owner_id = :owner"
                + filters
            ),
            {"owner": user.id, **params},
        )
        .mappings()
        .one()
    )

    month_start, next_month = month_range(today())
    kpi_row = (
        db.execute(
            text(
                """
                SELECT COALESCE(SUM(b.total) FILTER (WHERE i.issue_date >= :ms AND i.issue_date < :me), 0)
                         AS billed,
                       COALESCE(SUM(b.paid_amount), 0) AS paid,
                       COALESCE(SUM(b.balance), 0) AS outstanding,
                       count(*) FILTER (WHERE b.is_overdue) AS overdue_count,
                       COALESCE(SUM(b.balance) FILTER (WHERE b.is_overdue), 0) AS overdue_balance
                  FROM invoices i JOIN v_invoice_balances b ON b.invoice_id = i.id
                 WHERE i.owner_id = :owner AND i.status = 'issued'
                """
            ),
            {"owner": user.id, "ms": month_start, "me": next_month},
        )
        .mappings()
        .one()
    )

    where = filters + (f" AND {GROUP_SQL[group]}" if group else "")
    rows = summary_rows(db, user.id, where, params)
    window = rows[page.offset : page.offset + page.limit + 1]
    return InvoiceList(
        items=[to_summary(r) for r in window[: page.limit]],
        next_cursor=encode_cursor(page.offset + page.limit) if len(window) > page.limit else None,
        counts=InvoiceCounts(**counts_row),
        kpis=InvoiceKpis(
            billed_this_month=kpi_row["billed"],
            paid_total=kpi_row["paid"],
            outstanding_total=kpi_row["outstanding"],
            overdue_count=kpi_row["overdue_count"],
            overdue_balance=kpi_row["overdue_balance"],
        ),
    )


# ---------------------------------------------------------------- 초안
@router.post("/invoices", status_code=201, response_model=InvoiceDetail)
def create_invoice(
    body: InvoiceIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    project = get_owned_project(db, user.id, body.project_id)
    items, subtotal = build_items(db, project, body)
    invoice = Invoice(
        owner_id=user.id,
        project_id=project.id,
        title=body.title.strip(),
        due_date=body.due_date,
        subtotal=subtotal,
        tax_amount=body.tax_amount,
        withholding_amount=body.withholding_amount,
        adjustment_note=(body.adjustment_note or "").strip() or None,
        total=subtotal + body.tax_amount - body.withholding_amount,
        items=items,
    )
    db.add(invoice)
    db.commit()
    return build_detail(db, user.id, invoice.id)


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetail)
def read_invoice(
    invoice_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    return build_detail(db, user.id, invoice_id)


@router.put("/invoices/{invoice_id}", response_model=InvoiceDetail)
def update_invoice(
    invoice_id: UUID,
    body: InvoiceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvoiceDetail:
    """초안만 고칠 수 있다. 발행본은 취소 후 재발행한다 (설계서 6장)."""
    invoice = get_owned_invoice(db, user.id, invoice_id, lock=True)
    if invoice.status != "draft":
        raise conflict("invoice_not_draft", "issued invoices cannot be edited; cancel and reissue instead")
    assert_version(invoice.updated_at, body.version)
    if body.project_id != invoice.project_id:
        raise AppError(
            422, "validation_error", "the project of an invoice cannot change", {"fields": ["project_id"]}
        )
    project = get_owned_project(db, user.id, invoice.project_id)
    items, subtotal = build_items(db, project, body)

    invoice.items.clear()
    db.flush()
    invoice.items.extend(items)
    invoice.title = body.title.strip()
    invoice.due_date = body.due_date
    invoice.subtotal = subtotal
    invoice.tax_amount = body.tax_amount
    invoice.withholding_amount = body.withholding_amount
    invoice.adjustment_note = (body.adjustment_note or "").strip() or None
    invoice.total = subtotal + body.tax_amount - body.withholding_amount
    db.commit()
    return build_detail(db, user.id, invoice.id)


@router.delete("/invoices/{invoice_id}", status_code=204, response_class=Response)
def delete_invoice(
    invoice_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    invoice = get_owned_invoice(db, user.id, invoice_id, lock=True)
    if invoice.status != "draft":
        raise conflict("invoice_not_draft", "only drafts can be deleted")
    db.delete(invoice)
    db.commit()


# ---------------------------------------------------------------- 발행·취소·재발행
@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceDetail)
def issue_invoice(
    invoice_id: UUID,
    body: IssueIn,
    idempotency_key: str = Depends(require_idempotency_key),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """서버에서 다시 검증하고 발행 스냅샷을 고정한다. 같은 재전송 키로 다시 와도 한 번만 발행된다."""

    def handler() -> tuple[int, Any]:
        invoice = get_owned_invoice(db, user.id, invoice_id, lock=True)
        if invoice.status != "draft":
            raise conflict("invoice_not_draft", "the invoice is already issued or cancelled")
        if body.due_date is not None:
            invoice.due_date = body.due_date
        project = get_owned_project(db, user.id, invoice.project_id)
        check_issuable(db, invoice, project)

        issue_day = today()
        invoice.invoice_no = next_invoice_no(db, user.id, issue_day.year)
        invoice.issue_date = issue_day
        invoice.issued_at = now_utc()
        invoice.snapshot = build_snapshot(db, invoice, project, user)
        invoice.status = "issued"
        record_audit(
            db,
            actor_id=user.id,
            action="invoice.issue",
            target_type="invoice",
            target_id=invoice.id,
            invoice_no=invoice.invoice_no,
            total=str(invoice.total),
        )
        db.flush()
        return 200, build_detail(db, user.id, invoice.id).model_dump(mode="json")

    status, payload = run_idempotent(
        db,
        user.id,
        idempotency_key,
        {"op": "invoice.issue", "id": str(invoice_id), **body.model_dump(mode="json")},
        handler,
    )
    db.commit()
    return JSONResponse(payload, status_code=status)


@router.post("/invoices/{invoice_id}/cancel", response_model=InvoiceDetail)
def cancel_invoice(
    invoice_id: UUID, body: CancelIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    invoice = get_owned_invoice(db, user.id, invoice_id, lock=True)
    if invoice.status != "issued":
        raise conflict("invoice_not_issued", "only issued invoices can be cancelled")
    active = db.execute(
        select(Payment.id).where(Payment.invoice_id == invoice.id, Payment.voided_at.is_(None)).limit(1)
    ).first()
    if active:
        raise conflict("invoice_has_payments", "void the recorded payments before cancelling the invoice")
    invoice.status = "cancelled"
    invoice.cancelled_at = now_utc()
    invoice.cancel_reason = body.reason.strip()
    record_audit(
        db,
        actor_id=user.id,
        action="invoice.cancel",
        target_type="invoice",
        target_id=invoice.id,
        invoice_no=invoice.invoice_no,
        reason=invoice.cancel_reason,
    )
    db.commit()
    return build_detail(db, user.id, invoice.id)


@router.post("/invoices/{invoice_id}/reissue", status_code=201, response_model=InvoiceDetail)
def reissue_invoice(
    invoice_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    """취소된 인보이스의 항목을 복사해 새 초안을 만든다. 원본과의 연결은 replaces_invoice_id로 남긴다."""
    source = get_owned_invoice(db, user.id, invoice_id, lock=True)
    if source.status != "cancelled":
        raise conflict("invoice_not_cancelled", "only cancelled invoices can be reissued")
    if db.execute(select(Invoice.id).where(Invoice.replaces_invoice_id == source.id).limit(1)).first():
        raise conflict("already_reissued", "this invoice was already reissued")
    # 수정 계약을 반영한 뒤라면 옛 지급 단계를 이어진 현재 단계로 바꿔 배분한다
    project = get_owned_project(db, user.id, source.project_id)
    term_map: dict[UUID, UUID] = {}
    for item in source.items:
        for a in item.allocations:
            if a.payment_term_id and a.payment_term_id not in term_map:
                current = current_successor(db, a.payment_term_id, project.contract_version_id)
                if current is None:
                    raise conflict(
                        "reissue_term_replaced",
                        "the payment stage of this invoice no longer exists in the current contract; "
                        "create a new invoice instead",
                    )
                term_map[a.payment_term_id] = current
    copy = Invoice(
        owner_id=user.id,
        project_id=source.project_id,
        title=source.title,
        due_date=source.due_date,
        subtotal=source.subtotal,
        tax_amount=source.tax_amount,
        withholding_amount=source.withholding_amount,
        adjustment_note=source.adjustment_note,
        total=source.total,
        replaces_invoice_id=source.id,
        items=[
            InvoiceItem(
                position=i.position,
                kind=i.kind,
                description=i.description,
                detail=i.detail,
                quantity=i.quantity,
                unit_price=i.unit_price,
                amount=i.amount,
                basis_note=i.basis_note,
                basis_confirmed_at=i.basis_confirmed_at,
                allocations=[
                    BillingAllocation(
                        payment_term_id=term_map[a.payment_term_id] if a.payment_term_id else None,
                        task_id=a.task_id,
                        amount=a.amount,
                    )
                    for a in i.allocations
                ],
            )
            for i in source.items
        ],
    )
    db.add(copy)
    db.commit()
    return build_detail(db, user.id, copy.id)


@router.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: UUID,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    invoice = get_owned_invoice(db, user.id, invoice_id)
    if invoice.status == "draft" or not invoice.snapshot or not invoice.invoice_no:
        raise conflict("invoice_not_issued", "only issued invoices have a PDF")
    content = invoice_pdf(invoice.invoice_no, invoice.issue_date, invoice.due_date, invoice.snapshot)
    return _pdf_response(content, f"{invoice.invoice_no}.pdf", download)


# ---------------------------------------------------------------- 입금
@router.post("/invoices/{invoice_id}/payments", status_code=201, response_model=InvoiceDetail)
def record_payment(
    invoice_id: UUID,
    body: PaymentIn,
    idempotency_key: str = Depends(require_idempotency_key),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """사용자가 실제 입금을 확인한 뒤 기록한다 (은행 연동 아님). 초과 입금·취소 청구서 입금은 거절."""

    def handler() -> tuple[int, Any]:
        invoice = get_owned_invoice(db, user.id, invoice_id, lock=True)
        if invoice.status != "issued":
            raise conflict("invoice_not_issued", "payments can only be recorded on issued invoices")
        if body.paid_on > today():
            raise AppError(
                422, "future_date", "the payment date cannot be in the future", {"fields": ["paid_on"]}
            )
        paid = db.execute(
            text("SELECT paid_amount FROM v_invoice_balances WHERE invoice_id = :id"), {"id": invoice.id}
        ).scalar_one()
        balance = invoice.total - Decimal(paid)
        if body.amount > balance:
            raise conflict(
                "overpayment", "the amount exceeds the remaining balance", {"balance": str(balance)}
            )
        payment = Payment(
            invoice_id=invoice.id,
            amount=body.amount,
            paid_on=body.paid_on,
            method=body.method,
            memo=(body.memo or "").strip() or None,
            recorded_by=user.id,
        )
        db.add(payment)
        db.flush()
        record_audit(
            db,
            actor_id=user.id,
            action="payment.record",
            target_type="payment",
            target_id=payment.id,
            invoice_no=invoice.invoice_no,
            amount=str(body.amount),
        )
        return 201, build_detail(db, user.id, invoice.id).model_dump(mode="json")

    status, payload = run_idempotent(
        db,
        user.id,
        idempotency_key,
        {"op": "payment.record", "invoice": str(invoice_id), **body.model_dump(mode="json")},
        handler,
    )
    db.commit()
    return JSONResponse(payload, status_code=status)


def _owned_payment(
    db: Session, owner_id: UUID, payment_id: UUID, *, lock: bool = False
) -> tuple[Payment, Invoice]:
    stmt = (
        select(Payment, Invoice)
        .join(Invoice, Invoice.id == Payment.invoice_id)
        .where(Payment.id == payment_id, Invoice.owner_id == owner_id)
    )
    if lock:
        stmt = stmt.with_for_update(of=Payment)
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise not_found("payment")
    return row[0], row[1]


@router.post("/payments/{payment_id}/void", response_model=InvoiceDetail)
def void_payment(
    payment_id: UUID, body: CancelIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> InvoiceDetail:
    """잘못된 입금 기록은 지우지 않고 취소 이력을 남긴다. 그 입금으로 만든 확인서는 무효가 된다."""
    payment, invoice = _owned_payment(db, user.id, payment_id, lock=True)
    if payment.voided_at is not None:
        raise conflict("payment_voided", "the payment is already voided")
    payment.voided_at = now_utc()
    payment.void_reason = body.reason.strip()
    record_audit(
        db,
        actor_id=user.id,
        action="payment.void",
        target_type="payment",
        target_id=payment.id,
        amount=str(payment.amount),
        reason=payment.void_reason,
    )
    db.commit()
    return build_detail(db, user.id, invoice.id)


@router.get("/payments/{payment_id}/receipt")
def download_receipt(
    payment_id: UUID,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    payment, invoice = _owned_payment(db, user.id, payment_id)
    if payment.voided_at is not None:
        raise conflict("payment_voided", "a voided payment has no valid confirmation")
    if not invoice.snapshot or not invoice.invoice_no:
        raise conflict("invoice_not_issued", "the invoice was never issued")
    cumulative = db.execute(
        text(
            """
            SELECT COALESCE(SUM(amount), 0) FROM payments
             WHERE invoice_id = :invoice AND voided_at IS NULL
               AND (created_at, id) <= (:created_at, :id)
            """
        ),
        {"invoice": invoice.id, "created_at": payment.created_at, "id": payment.id},
    ).scalar_one()
    content = receipt_pdf(
        ReceiptFacts(
            invoice_no=invoice.invoice_no,
            invoice_title=invoice.title,
            invoice_total=invoice.total,
            paid_on=payment.paid_on,
            amount=payment.amount,
            cumulative_paid=Decimal(cumulative),
            method=payment.method,
            memo=payment.memo,
            snapshot=invoice.snapshot,
        )
    )
    return _pdf_response(
        content, f"입금확인서_{invoice.invoice_no}_{payment.paid_on.isoformat()}.pdf", download
    )
