from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Hours, JobType, Won

ItemKind = Literal["payment_stage", "task", "hourly", "extra"]
InvoiceStatus = Literal["draft", "issued", "cancelled"]
PaymentStatus = Literal["unpaid", "partial", "paid"]
InvoiceGroup = Literal["draft", "unpaid", "partial", "paid", "overdue", "cancelled", "outstanding"]


# ---------------------------------------------------------------- 계약서 → 프로젝트 (07)
class PaymentTermIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["deposit", "interim", "balance", "other"]
    label: str = Field(min_length=1, max_length=50)
    ratio: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)
    amount: Won
    requirement: str | None = Field(default=None, max_length=200)
    due_date: date | None = None


class PaymentTermDraft(PaymentTermIn):
    seq: int


class TaskDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=20)
    due_date: date | None = None


class ProjectDraft(BaseModel):
    """계약서의 확인값으로 만든 프로젝트 초안. 저장하지 않는다."""

    contract_id: UUID
    contract_title: str
    version_no: int
    name: str
    client_id: UUID | None
    job_type: JobType
    start_date: date | None
    due_date: date | None
    contract_amount: Won
    payment_terms_text: str | None
    payment_terms: list[PaymentTermDraft]
    tasks: list[TaskDraftIn]
    linked_project_id: UUID | None


class ProjectFromContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    client_id: UUID | None = None
    new_client_name: str | None = Field(default=None, min_length=1, max_length=100)
    job_type: JobType
    start_date: date | None = None
    due_date: date | None = None
    contract_amount: Won
    payment_terms: list[PaymentTermIn] = Field(min_length=1, max_length=10)
    tasks: list[TaskDraftIn] = Field(default_factory=list, max_length=50)
    # 있으면 새로 만들지 않고, 계약서가 아직 없는 기존 프로젝트에 이 계약을 연결한다
    project_id: UUID | None = None
    # 이미 계약서가 붙은 프로젝트면 교체한다. 기존 계약으로 청구한 적이 없을 때만 된다
    replace_contract: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.project_id is not None:
            if self.client_id is not None and self.new_client_name is not None:
                raise ValueError("provide at most one of client_id or new_client_name")
        elif (self.client_id is None) == (self.new_client_name is None):
            raise ValueError("provide exactly one of client_id or new_client_name")
        if self.start_date and self.due_date and self.due_date < self.start_date:
            raise ValueError("due_date must be on or after start_date")
        return self


# ---------------------------------------------------------------- 청구 후보
class TermCandidate(BaseModel):
    payment_term_id: UUID
    seq: int
    stage: str
    label: str
    amount: Won
    requirement: str | None
    billed_amount: Won = Field(description="발행된 인보이스에 배분된 금액")
    drafted_amount: Won = Field(description="초안 인보이스에 잡혀 있는 금액")
    carried_amount: Won = Field(
        default=Decimal(0), description="수정 전 계약에서 이어진 발행 청구액 (billed_amount에 포함)"
    )
    remaining_amount: Won


class TaskCandidate(BaseModel):
    task_id: UUID
    title: str
    status: str
    completed_at: datetime | None
    hours: Hours | None
    hourly_rate: Won | None
    billed_amount: Won


class BillingCandidates(BaseModel):
    project_id: UUID
    contract_version_id: UUID | None
    payment_terms: list[TermCandidate]
    tasks: list[TaskCandidate]


# ---------------------------------------------------------------- 인보이스
class InvoiceItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ItemKind
    description: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=500)
    quantity: Hours = Field(default=Decimal(1), gt=0)
    unit_price: Won
    payment_term_id: UUID | None = None
    task_id: UUID | None = None
    # 지급 요건 확인 (예: "최종 납품 및 검수 확인"). 요건이 있는 지급 단계는 발행 전에 필수
    basis_note: str | None = Field(default=None, max_length=200)
    basis_confirmed: bool = False

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.kind == "payment_stage" and (self.payment_term_id is None or self.task_id is not None):
            raise ValueError("payment_stage items need payment_term_id only")
        if self.kind in ("task", "hourly") and (self.task_id is None or self.payment_term_id is not None):
            raise ValueError(f"{self.kind} items need task_id only")
        if self.kind == "extra" and (self.task_id or self.payment_term_id):
            raise ValueError("extra items cannot link a payment term or task")
        if self.kind == "payment_stage" and self.quantity != 1:
            raise ValueError("payment_stage items have quantity 1")
        return self


class InvoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    title: str = Field(min_length=1, max_length=100)
    due_date: date | None = None
    items: list[InvoiceItemIn] = Field(min_length=1, max_length=30)
    tax_amount: Won = Field(default=Decimal(0))
    withholding_amount: Won = Field(default=Decimal(0))
    adjustment_note: str | None = Field(default=None, max_length=300)


class InvoiceUpdate(InvoiceIn):
    """초안 수정: 항목을 통째로 바꾼다. project_id는 바꿀 수 없다."""

    version: datetime | None = None


class IssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    due_date: date | None = None


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=300)


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Won = Field(gt=0)
    paid_on: date
    method: Literal["bank_transfer", "cash", "card", "other"] = "bank_transfer"
    memo: str | None = Field(default=None, max_length=300)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Won
    paid_on: date
    method: str
    memo: str | None
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime


class InvoiceItemOut(BaseModel):
    id: UUID
    position: int
    kind: ItemKind
    description: str
    detail: str | None
    quantity: Hours
    unit_price: Won
    amount: Won
    payment_term_id: UUID | None
    task_id: UUID | None
    basis_note: str | None
    basis_confirmed_at: datetime | None


class InvoiceSummary(BaseModel):
    id: UUID
    invoice_no: str | None
    title: str
    status: InvoiceStatus
    project_id: UUID
    project_name: str
    client_name: str
    total: Won
    paid_amount: Won
    balance: Won
    payment_status: PaymentStatus | None
    is_overdue: bool
    issue_date: date | None
    due_date: date | None
    created_at: datetime


class InvoiceDetail(InvoiceSummary):
    subtotal: Won
    tax_amount: Won
    withholding_amount: Won
    adjustment_note: str | None
    items: list[InvoiceItemOut]
    payments: list[PaymentOut]
    snapshot: dict[str, Any] | None
    replaces_invoice_id: UUID | None
    replaced_by_invoice_id: UUID | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    version: datetime


class InvoiceKpis(BaseModel):
    billed_this_month: Won
    paid_total: Won
    outstanding_total: Won
    overdue_count: int
    overdue_balance: Won


class InvoiceCounts(BaseModel):
    all: int
    draft: int
    unpaid: int
    partial: int
    paid: int
    overdue: int
    cancelled: int
    outstanding: int = 0


class InvoiceList(BaseModel):
    items: list[InvoiceSummary]
    next_cursor: str | None
    counts: InvoiceCounts
    kpis: InvoiceKpis
