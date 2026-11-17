from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Hours, JobType, Won

ProjectStatus = Literal["active", "completed", "archived"]
TaskStatus = Literal["todo", "doing", "done"]
TaskSource = Literal["contract", "estimated", "manual", "template"]


def _check_dates(start: date | None, due: date | None) -> None:
    if start and due and due < start:
        raise ValueError("due_date must be on or after start_date")


# ---------------------------------------------------------------- 거래처
class ClientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    contact_name: str | None = Field(default=None, max_length=50)
    contact_email: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    contact_name: str | None = Field(default=None, max_length=50)
    contact_email: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    memo: str | None = Field(default=None, max_length=1000)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    contact_name: str | None
    contact_email: str | None
    contact_phone: str | None
    memo: str | None


class ClientRef(BaseModel):
    id: UUID
    name: str


# ---------------------------------------------------------------- 프로젝트
class ProjectCreate(BaseModel):
    """수동 생성. 거래처는 기존 것을 고르거나(client_id) 새 이름을 입력한다(new_client_name)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    client_id: UUID | None = None
    new_client_name: str | None = Field(default=None, min_length=1, max_length=100)
    job_type: JobType | None = None
    start_date: date | None = None
    due_date: date | None = None
    draft_delivery_date: date | None = None
    draft_delivery_exempt: bool | None = None
    contract_amount: Won = Field(default=Decimal(0))
    # true면 직군별 기본 단계를 작업으로 만든다
    use_template: bool = False
    included_revisions: int | None = Field(default=None, ge=0, le=99)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if (self.client_id is None) == (self.new_client_name is None):
            raise ValueError("provide exactly one of client_id or new_client_name")
        _check_dates(self.start_date, self.due_date)
        if self.draft_delivery_exempt and self.draft_delivery_date:
            raise ValueError("draft delivery date must be empty when exempt")
        if self.draft_delivery_date and self.due_date and self.draft_delivery_date > self.due_date:
            raise ValueError("draft delivery date must be on or before upload date")
        return self


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    client_id: UUID | None = None
    job_type: JobType | None = None
    start_date: date | None = None
    due_date: date | None = None
    draft_delivery_date: date | None = None
    draft_delivery_exempt: bool | None = None
    contract_amount: Won | None = None
    status: ProjectStatus | None = None
    included_revisions: int | None = Field(default=None, ge=0, le=99)
    # 읽은 시점의 updated_at. 그 사이 바뀌었으면 409
    version: datetime | None = None


class PaymentTermOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seq: int
    stage: str
    label: str
    amount: Won
    requirement: str | None
    due_date: date | None
    # 청구 현황: 미청구 → 초안 → 청구됨(발행) → 입금 완료
    billing_status: Literal["unbilled", "draft", "billed", "paid"] = "unbilled"
    billed_amount: Won = Field(default=Decimal(0))
    carried_amount: Won = Field(
        default=Decimal(0), description="수정 전 계약에서 이어진 청구액 (billed_amount에 포함)"
    )
    invoice_id: UUID | None = Field(default=None, description="이 단계를 청구한 가장 최근 인보이스")


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    job_type: JobType
    status: ProjectStatus
    client: ClientRef
    start_date: date | None
    due_date: date | None
    contract_amount: Won
    total_tasks: int
    done_tasks: int
    progress_pct: int | None = Field(description="작업이 없으면 null (산정 전)")
    billed_amount: Won
    paid_amount: Won
    outstanding_amount: Won
    has_contract: bool
    version: datetime


class ProjectDetail(ProjectSummary):
    contract_id: UUID | None = None
    included_revisions: int | None = None
    draft_delivery_date: date | None = None
    draft_delivery_exempt: bool | None = None
    payment_terms: list[PaymentTermOut]


class ProjectCounts(BaseModel):
    all: int
    active: int
    completed: int
    archived: int


class ProjectList(BaseModel):
    items: list[ProjectSummary]
    next_cursor: str | None
    counts: ProjectCounts


# ---------------------------------------------------------------- 작업
class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    is_done: bool
    position: int


class ChecklistItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=200)


class ChecklistItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=200)
    is_done: bool | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    label: str | None
    status: TaskStatus
    position: int
    due_date: date | None
    completed_at: datetime | None
    hours: Hours | None
    hourly_rate: Won | None
    source: TaskSource
    source_note: str | None
    checklist: list[ChecklistItemOut]
    version: datetime = Field(validation_alias="updated_at")


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=20)
    status: TaskStatus = "todo"
    due_date: date | None = None
    hours: Hours | None = None
    hourly_rate: Won | None = None


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=20)
    due_date: date | None = None
    hours: Hours | None = None
    hourly_rate: Won | None = None
    version: datetime | None = None


class TaskMove(BaseModel):
    """칸반 이동: 대상 열(status)과 그 열 안에서의 위치(0부터)."""

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus
    index: int = Field(ge=0)
