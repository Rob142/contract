from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import Won
from app.schemas.projects import ProjectSummary


class UpcomingTask(BaseModel):
    task_id: UUID
    title: str
    project_id: UUID
    project_name: str
    due_date: date


class OutstandingInvoice(BaseModel):
    invoice_id: UUID
    invoice_no: str
    title: str
    project_id: UUID
    client_name: str
    total: Won
    paid_amount: Won
    balance: Won
    due_date: date
    payment_status: Literal["unpaid", "partial", "paid"]
    is_overdue: bool


class Todo(BaseModel):
    """대시보드 "지금 할 일". 화면이 target으로 바로 이동한다."""

    kind: Literal[
        "invoice_overdue",
        "invoice_due_soon",
        "contract_review",
        "contract_failed",
        "invoice_draft",
        "stage_to_bill",
        "contract_to_project",
        "task_due",
        "contract_revision",
    ]
    title: str
    detail: str
    target: Literal["contract", "contract_project", "invoice", "invoice_new", "project", "project_revision"]
    target_id: UUID
    due_date: date | None = None
    tone: Literal["warning", "action", "info"]


class Dashboard(BaseModel):
    today: date
    active_projects: int
    tasks_completed_this_month: int
    tasks_due_this_week: int
    tasks_due_today: int
    nearest_due_date: date | None
    # 발행된 인보이스 기준. 초안은 제외한다
    billed_this_month: Won
    paid_total: Won
    outstanding_total: Won
    projects: list[ProjectSummary]
    upcoming: list[UpcomingTask]
    invoices: list[OutstandingInvoice]
    todos: list[Todo]
