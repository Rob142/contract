from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import month_range, today, week_range
from app.core.errors import AppError
from app.db.models import Project, Task, User
from app.db.session import get_db
from app.schemas.dashboard import Dashboard, OutstandingInvoice, Todo, UpcomingTask
from app.services.projects import list_summaries

router = APIRouter(tags=["dashboard"])

UPCOMING_LIMIT = 5
TODO_LIMIT = 8
DUE_SOON_DAYS = 3


def build_todos(db: Session, owner_id: object, day: date) -> list[Todo]:
    """흩어진 다음 행동을 한곳에 모은다. 급한 것(연체)부터, 최대 TODO_LIMIT개."""
    todos: list[Todo] = []
    params = {"owner": owner_id, "today": day, "soon": day + timedelta(days=DUE_SOON_DAYS)}

    for r in db.execute(
        text(
            """
            SELECT b.invoice_id, i.invoice_no, i.title, b.balance, b.due_date
              FROM v_invoice_balances b JOIN invoices i ON i.id = b.invoice_id
             WHERE b.owner_id = :owner AND b.is_overdue ORDER BY b.due_date
            """
        ),
        params,
    ).mappings():
        todos.append(
            Todo(
                kind="invoice_overdue",
                title=f"연체 입금 확인 · {r['invoice_no']}",
                detail=f"{r['title']} · 잔액 {int(r['balance']):,}원",
                target="invoice",
                target_id=r["invoice_id"],
                due_date=r["due_date"],
                tone="warning",
            )
        )

    # 기한이 3일 이내로 다가오는 미수금. 연체 전에 입금을 확인하도록 알려준다
    for r in db.execute(
        text(
            """
            SELECT b.invoice_id, i.invoice_no, i.title, b.balance, b.due_date
              FROM v_invoice_balances b JOIN invoices i ON i.id = b.invoice_id
             WHERE b.owner_id = :owner AND b.status = 'issued' AND b.balance > 0
               AND NOT b.is_overdue AND b.due_date >= :today AND b.due_date <= :soon
             ORDER BY b.due_date
            """
        ),
        params,
    ).mappings():
        todos.append(
            Todo(
                kind="invoice_due_soon",
                title=f"곧 기한인 입금 확인 · {r['invoice_no']}",
                detail=f"{r['title']} · 잔액 {int(r['balance']):,}원",
                target="invoice",
                target_id=r["invoice_id"],
                due_date=r["due_date"],
                tone="info",
            )
        )

    contract_rows = (
        db.execute(
            text(
                """
            SELECT c.id, c.title, v.status,
                   EXISTS (SELECT 1 FROM projects p WHERE p.contract_version_id = v.id) AS has_project
              FROM contracts c
              JOIN LATERAL (SELECT * FROM contract_versions cv WHERE cv.contract_id = c.id
                             ORDER BY cv.version_no DESC LIMIT 1) v ON true
             WHERE c.owner_id = :owner AND v.status IN ('needs_review', 'failed', 'ready', 'analyzed')
             ORDER BY v.created_at DESC
            """
            ),
            params,
        )
        .mappings()
        .all()
    )
    for r in contract_rows:
        if r["status"] == "needs_review":
            todos.append(
                Todo(
                    kind="contract_review",
                    title="계약서 조건 확인하기",
                    detail=r["title"],
                    target="contract",
                    target_id=r["id"],
                    tone="action",
                )
            )
        elif r["status"] == "failed":
            todos.append(
                Todo(
                    kind="contract_failed",
                    title="텍스트 추출 다시 시도",
                    detail=r["title"],
                    target="contract",
                    target_id=r["id"],
                    tone="warning",
                )
            )

    for r in db.execute(
        text(
            "SELECT id, title, total FROM invoices"
            " WHERE owner_id = :owner AND status = 'draft' ORDER BY created_at"
        ),
        params,
    ).mappings():
        todos.append(
            Todo(
                kind="invoice_draft",
                title="인보이스 초안 발행하기",
                detail=f"{r['title']} · {int(r['total']):,}원",
                target="invoice",
                target_id=r["id"],
                tone="action",
            )
        )

    # 확인을 마친 수정 계약서가 프로젝트에 아직 반영되지 않았다
    for r in db.execute(
        text(
            """
            SELECT p.id AS project_id, p.name, cur.version_no AS from_no, nv.version_no AS to_no
              FROM projects p
              JOIN contract_versions cur ON cur.id = p.contract_version_id
              JOIN LATERAL (SELECT * FROM contract_versions v WHERE v.contract_id = cur.contract_id
                             ORDER BY v.version_no DESC LIMIT 1) nv ON true
             WHERE p.owner_id = :owner AND p.status <> 'archived'
               AND nv.version_no > cur.version_no AND nv.status IN ('ready', 'analyzed')
            """
        ),
        params,
    ).mappings():
        todos.append(
            Todo(
                kind="contract_revision",
                title="수정 계약 반영하기",
                detail=f"{r['name']} · v{r['from_no']} → v{r['to_no']}",
                target="project_revision",
                target_id=r["project_id"],
                tone="action",
            )
        )

    # 아직 청구하지 않은 지급 단계
    # 선금은 바로, 중도금·잔금은 작업을 모두 마쳤거나 프로젝트를 완료로 바꿨을 때
    for r in db.execute(
        text(
            """
            SELECT p.id AS project_id, p.name, pt.label, pt.amount
              FROM projects p
              JOIN payment_terms pt ON pt.contract_version_id = p.contract_version_id
              JOIN v_project_summary s ON s.project_id = p.id
             WHERE p.owner_id = :owner AND p.status IN ('active', 'completed')
               AND NOT EXISTS (
                   SELECT 1 FROM billing_allocations ba
                     JOIN invoice_items ii ON ii.id = ba.invoice_item_id
                     JOIN invoices i ON i.id = ii.invoice_id
                    WHERE ba.payment_term_id = pt.id AND i.status <> 'cancelled')
               AND (pt.stage = 'deposit' OR p.status = 'completed'
                    OR (s.total_tasks > 0 AND s.done_tasks = s.total_tasks))
             ORDER BY p.due_date NULLS LAST, pt.seq
            """
        ),
        params,
    ).mappings():
        todos.append(
            Todo(
                kind="stage_to_bill",
                title=f"{r['label']} 청구하기",
                detail=f"{r['name']} · {int(r['amount']):,}원",
                target="invoice_new",
                target_id=r["project_id"],
                tone="action",
            )
        )

    for r in contract_rows:
        if r["status"] in ("ready", "analyzed") and not r["has_project"]:
            todos.append(
                Todo(
                    kind="contract_to_project",
                    title="계약서로 프로젝트 만들기",
                    detail=r["title"],
                    target="contract_project",
                    target_id=r["id"],
                    tone="info",
                )
            )

    for r in db.execute(
        text(
            """
            SELECT t.title, t.due_date, p.id AS project_id, p.name
              FROM tasks t JOIN projects p ON p.id = t.project_id
             WHERE p.owner_id = :owner AND p.status = 'active' AND t.status <> 'done'
               AND t.due_date <= :soon
             ORDER BY t.due_date, t.position
            """
        ),
        params,
    ).mappings():
        overdue = r["due_date"] < day
        todos.append(
            Todo(
                kind="task_due",
                title=f"{'마감 지남' if overdue else '마감 임박'} · {r['title']}",
                detail=r["name"],
                target="project",
                target_id=r["project_id"],
                due_date=r["due_date"],
                tone="warning" if overdue else "info",
            )
        )

    return todos[:TODO_LIMIT]


PROJECT_LIMIT = 5
INVOICE_LIMIT = 5


@router.get("/dashboard", response_model=Dashboard)
def dashboard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Dashboard:
    day = today()
    _, week_end = week_range(day)
    month_start, next_month = month_range(day)

    # 진행 중 프로젝트의 미완료 작업
    open_tasks = and_(Project.owner_id == user.id, Project.status == "active", Task.status != "done")
    task_base = select(Task).join(Project, Project.id == Task.project_id)

    active_projects = db.execute(
        select(func.count()).where(Project.owner_id == user.id, Project.status == "active")
    ).scalar_one()

    due_this_week = db.execute(
        select(func.count()).select_from(
            task_base.where(open_tasks, Task.due_date.between(day, week_end)).subquery()
        )
    ).scalar_one()
    due_today = db.execute(
        select(func.count()).select_from(task_base.where(open_tasks, Task.due_date == day).subquery())
    ).scalar_one()
    nearest_due = db.execute(
        select(func.min(Task.due_date))
        .join(Project, Project.id == Task.project_id)
        .where(open_tasks, Task.due_date >= day)
    ).scalar_one()

    completed_this_month = db.execute(
        select(func.count())
        .select_from(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.owner_id == user.id,
            Task.status == "done",
            Task.completed_at >= month_start,
            Task.completed_at < next_month,
        )
    ).scalar_one()

    upcoming_rows = db.execute(
        select(Task.id, Task.title, Task.due_date, Project.id.label("project_id"), Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(open_tasks, Task.due_date >= day)
        .order_by(Task.due_date, Task.position)
        .limit(UPCOMING_LIMIT)
    ).all()

    money = (
        db.execute(
            text(
                """
                SELECT
                  COALESCE(SUM(b.total) FILTER (WHERE i.issue_date >= :month_start
                                                AND i.issue_date < :next_month), 0) AS billed_this_month,
                  COALESCE((SELECT SUM(p.amount)
                              FROM payments p JOIN invoices pi ON pi.id = p.invoice_id
                             WHERE pi.owner_id = :owner AND pi.status = 'issued' AND p.voided_at IS NULL
                               AND p.paid_on >= :month_start AND p.paid_on < :next_month), 0)
                    AS received_this_month,
                  COALESCE(SUM(b.paid_amount), 0) AS paid_total,
                  COALESCE(SUM(b.balance), 0)     AS outstanding_total
                FROM v_invoice_balances b
                JOIN invoices i ON i.id = b.invoice_id
                WHERE b.owner_id = :owner AND b.status = 'issued'
                """
            ),
            {"owner": user.id, "month_start": month_start, "next_month": next_month},
        )
        .mappings()
        .one()
    )

    invoice_rows = (
        db.execute(
            text(
                """
                SELECT b.invoice_id, b.invoice_no, i.title, b.project_id, c.name AS client_name,
                       b.total, b.paid_amount, b.balance, b.due_date, b.payment_status, b.is_overdue
                FROM v_invoice_balances b
                JOIN invoices i ON i.id = b.invoice_id
                JOIN projects p ON p.id = b.project_id
                JOIN clients c ON c.id = p.client_id
                WHERE b.owner_id = :owner AND b.status = 'issued' AND b.balance > 0
                ORDER BY b.is_overdue DESC, b.due_date, b.invoice_no
                LIMIT :limit
                """
            ),
            {"owner": user.id, "limit": INVOICE_LIMIT},
        )
        .mappings()
        .all()
    )

    return Dashboard(
        today=day,
        active_projects=active_projects,
        tasks_completed_this_month=completed_this_month,
        tasks_due_this_week=due_this_week,
        tasks_due_today=due_today,
        nearest_due_date=nearest_due,
        billed_this_month=money["billed_this_month"],
        received_this_month=money["received_this_month"],
        paid_total=money["paid_total"],
        outstanding_total=money["outstanding_total"],
        projects=list_summaries(db, user.id, "active", PROJECT_LIMIT, 0),
        upcoming=[
            UpcomingTask(
                task_id=r.id, title=r.title, project_id=r.project_id, project_name=r.name, due_date=r.due_date
            )
            for r in upcoming_rows
        ],
        invoices=[OutstandingInvoice(**r) for r in invoice_rows],
        todos=build_todos(db, user.id, day),
    )


@router.get("/dashboard/calendar", response_model=list[UpcomingTask])
def calendar_tasks(
    month: str = Query(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UpcomingTask]:
    """선택한 달의 미완료 작업. 건수 제한으로 일정을 누락시키지 않는다."""
    try:
        start, end = month_range(date.fromisoformat(f"{month}-01"))
    except (ValueError, OverflowError) as exc:
        raise AppError(422, "validation_error", "invalid calendar month") from exc
    rows = db.execute(
        select(Task.id, Task.title, Task.due_date, Project.id.label("project_id"), Project.name)
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.owner_id == user.id,
            Project.status == "active",
            Task.status != "done",
            Task.due_date >= start,
            Task.due_date < end,
        )
        .order_by(Task.due_date, Task.position, Task.id)
    ).all()
    return [
        UpcomingTask(
            task_id=r.id, title=r.title, project_id=r.project_id, project_name=r.name, due_date=r.due_date
        )
        for r in rows
    ]
