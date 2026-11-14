from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import JobType, Won

AttachmentKind = Literal["deliverable", "evidence", "other"]
DocType = Literal["tax_invoice", "cash_receipt", "receipt", "contract_copy", "other"]


# ---------------------------------------------------------------- 첨부
class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    task_id: UUID | None
    invoice_id: UUID | None
    kind: AttachmentKind
    doc_type: DocType | None
    title: str
    url: str | None
    has_file: bool = False
    file_name: str | None = None
    file_size: int | None = None
    issued_on: date | None
    amount: Won | None
    memo: str | None
    created_at: datetime


class LinkAttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=2000)
    kind: AttachmentKind = "deliverable"
    task_id: UUID | None = None

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        v = v.strip()
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return v


# ---------------------------------------------------------------- 공유 링크
class ShareLinkOut(BaseModel):
    id: UUID
    # 토큰 원문은 만들 때 한 번만 돌려준다
    token: str | None = None
    expires_at: datetime | None
    show_invoices: bool
    allow_feedback: bool
    last_viewed_at: datetime | None
    created_at: datetime


class ShareLinkUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    show_invoices: bool | None = None
    allow_feedback: bool | None = None
    expires_at: datetime | None = None


class ShareLinkState(BaseModel):
    link: ShareLinkOut | None


# ---------------------------------------------------------------- 피드백·확인
class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)
    author_name: str | None = Field(default=None, min_length=1, max_length=50)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    author_role: Literal["freelancer", "client"]
    author_name: str
    body: str
    created_at: datetime


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    viewer_name: str | None = Field(default=None, min_length=1, max_length=50)


class ViewEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID | None
    kind: Literal["open", "stage_ack", "deliverable"]
    viewer_name: str | None
    created_at: datetime


# ---------------------------------------------------------------- 수정 요청 카운터
class RevisionRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)
    requester_name: str | None = Field(default=None, min_length=1, max_length=50)
    task_id: UUID | None = None


class RevisionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID | None
    seq: int
    body: str
    requester_name: str
    over_limit: bool
    excluded_at: datetime | None
    excluded_reason: str | None
    created_at: datetime


class RevisionCounter(BaseModel):
    included: int | None = Field(description="포함 수정 횟수. null이면 카운터를 쓰지 않는다")
    used: int
    remaining: int | None


class RevisionState(BaseModel):
    counter: RevisionCounter
    requests: list[RevisionRequestOut]
    quotes: list["ExtraQuoteOut"]


class RevisionExcludeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=200)


class ExtraQuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    amount: Won
    description: str | None = Field(default=None, max_length=1000)
    revision_request_id: UUID | None = None


class ExtraQuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision_request_id: UUID | None
    title: str
    description: str | None
    amount: Won
    created_at: datetime


# ---------------------------------------------------------------- 템플릿
class JobTemplateOut(BaseModel):
    job_type: JobType
    steps: list[str]


# ---------------------------------------------------------------- 클라이언트 공개 응답 (허용 목록)
class PublicAttachment(BaseModel):
    id: UUID
    title: str
    url: str | None
    has_file: bool
    created_at: datetime


class PublicTask(BaseModel):
    id: UUID
    title: str
    status: Literal["todo", "doing", "done"]
    due_date: date | None
    completed_at: datetime | None
    deliverables: list[PublicAttachment]
    feedback: list[FeedbackOut]
    acknowledged_at: datetime | None


class PublicContract(BaseModel):
    contract_amount: Won
    start_date: date | None
    due_date: date | None
    included_revisions: int | None


class PublicInvoice(BaseModel):
    invoice_no: str
    total: Won
    due_date: date | None
    status: Literal["issued", "paid"]


class PublicProject(BaseModel):
    name: str
    job_type: JobType
    progress_pct: int | None
    freelancer_name: str
    contract: PublicContract
    revision: RevisionCounter
    allow_feedback: bool
    tasks: list[PublicTask]
    invoices: list[PublicInvoice] | None
    revision_requests: list[RevisionRequestOut]


RevisionState.model_rebuild()
