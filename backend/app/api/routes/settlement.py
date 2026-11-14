"""서류·정산: 월별 수입(입금일 기준)과 증빙 모아 보기. 기준 시간대는 설정의 timezone(KST)이다."""

import re
from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.core.errors import AppError
from app.db.models import Attachment, Project, StoredFile, User
from app.db.session import get_db
from app.schemas.settlement import EvidenceDoc, MonthDetail, MonthlyIncome, MonthlyIncomeOut, MonthProject

router = APIRouter(prefix="/settlement", tags=["settlement"])

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month_start(value: str) -> date:
    if not MONTH.match(value):
        raise AppError(422, "validation_error", "month must be YYYY-MM", {"fields": ["month"]})
    return date(int(value[:4]), int(value[5:]), 1)


def _next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def _add_months(day: date, delta: int) -> date:
    index = day.year * 12 + day.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


@router.get("/monthly-income", response_model=MonthlyIncomeOut)
def monthly_income(
    months: int = Query(default=12, ge=1, le=36),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonthlyIncomeOut:
    """입금일 기준 입금액을 수입으로 센다. 취소된 입금과 초안·취소된 인보이스는 제외한다.

    입금이 없는 달도 0으로 채워 돌려준다. 청구액은 발행일 기준 참고 지표다.
    """
    first = _add_months(today().replace(day=1), -(months - 1))
    received = {
        r.m: r.total
        for r in db.execute(
            text(
                """
                SELECT to_char(p.paid_on, 'YYYY-MM') AS m, sum(p.amount) AS total
                  FROM payments p JOIN invoices i ON i.id = p.invoice_id
                 WHERE i.owner_id = :owner AND p.voided_at IS NULL AND i.status = 'issued'
                   AND p.paid_on >= :first
                 GROUP BY 1
                """
            ),
            {"owner": user.id, "first": first},
        )
    }
    billed = {
        r.m: r.total
        for r in db.execute(
            text(
                """
                SELECT to_char(issue_date, 'YYYY-MM') AS m, sum(total) AS total
                  FROM invoices
                 WHERE owner_id = :owner AND status = 'issued' AND issue_date >= :first
                 GROUP BY 1
                """
            ),
            {"owner": user.id, "first": first},
        )
    }
    rows = []
    for offset in range(months):
        key = _add_months(first, offset).strftime("%Y-%m")
        rows.append(
            MonthlyIncome(
                month=key, received=received.get(key, Decimal(0)), billed=billed.get(key, Decimal(0))
            )
        )
    return MonthlyIncomeOut(
        months=rows,
        received_total=sum((r.received for r in rows), Decimal(0)),
        billed_total=sum((r.billed for r in rows), Decimal(0)),
    )


@router.get("/monthly-income/{month}", response_model=MonthDetail)
def month_detail(
    month: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> MonthDetail:
    start = _month_start(month)
    rows = db.execute(
        text(
            """
            SELECT pr.id AS project_id, pr.name, sum(p.amount) AS total
              FROM payments p
              JOIN invoices i ON i.id = p.invoice_id
              JOIN projects pr ON pr.id = i.project_id
             WHERE i.owner_id = :owner AND p.voided_at IS NULL AND i.status = 'issued'
               AND p.paid_on >= :start AND p.paid_on < :end
             GROUP BY pr.id, pr.name ORDER BY total DESC, pr.name
            """
        ),
        {"owner": user.id, "start": start, "end": _next_month(start)},
    ).all()
    return MonthDetail(
        month=month,
        received=sum((r.total for r in rows), Decimal(0)),
        projects=[MonthProject(project_id=r.project_id, name=r.name, received=r.total) for r in rows],
    )


@router.get("/evidence", response_model=list[EvidenceDoc])
def list_evidence(
    project_id: UUID | None = Query(default=None),
    doc_type: str | None = Query(default=None),
    month: str | None = Query(default=None, description="YYYY-MM (발행일 기준)"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EvidenceDoc]:
    stmt = (
        select(Attachment, Project.name, StoredFile.id)
        .join(Project, Project.id == Attachment.project_id)
        .outerjoin(StoredFile, StoredFile.id == Attachment.file_id)
        .where(Attachment.owner_id == user.id, Attachment.kind == "evidence")
        .order_by(Attachment.issued_on.desc().nulls_last(), Attachment.created_at.desc())
    )
    if project_id:
        stmt = stmt.where(Attachment.project_id == project_id)
    if doc_type:
        stmt = stmt.where(Attachment.doc_type == doc_type)
    if month:
        start = _month_start(month)
        stmt = stmt.where(Attachment.issued_on >= start, Attachment.issued_on < _next_month(start))
    return [
        EvidenceDoc(
            id=a.id,
            project_id=a.project_id,
            project_name=name,
            title=a.title,
            doc_type=a.doc_type,
            issued_on=a.issued_on,
            amount=a.amount,
            url=a.url,
            has_file=fid is not None,
        )
        for a, name, fid in db.execute(stmt).all()
    ]
