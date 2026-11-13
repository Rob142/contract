from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import JobType
from app.schemas.projects import ClientRef

VersionStatus = Literal["uploaded", "extracting", "needs_review", "ready", "analyzing", "analyzed", "failed"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
FieldKey = Literal["contract_amount", "final_due_date", "payment_terms", "revision_count"]
StatusGroup = Literal["processing", "needs_review", "ready", "analyzed", "failed"]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    status: JobStatus
    stage: str | None
    attempts: int
    max_attempts: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancel_requested: bool


class ContractSummary(BaseModel):
    id: UUID
    title: str
    job_type: JobType
    client: ClientRef | None
    version_id: UUID
    version_no: int
    status: VersionStatus
    failure_reason: str | None
    page_count: int | None
    uploaded_at: datetime
    project_id: UUID | None = Field(default=None, description="이 계약(어느 버전이든)을 쓰는 프로젝트")
    project_version_no: int | None = Field(
        default=None, description="프로젝트가 쓰는 계약 버전. 최신 버전보다 낮으면 수정 계약 반영 전이다"
    )


class ContractCounts(BaseModel):
    all: int
    processing: int
    needs_review: int
    ready: int
    analyzed: int
    failed: int


class ContractList(BaseModel):
    items: list[ContractSummary]
    next_cursor: str | None
    counts: ContractCounts


class Evidence(BaseModel):
    block_key: str
    page_no: int
    text: str


class FieldOut(BaseModel):
    key: FieldKey
    extracted_value: str | None
    confirmed_value: str | None
    status: Literal["unconfirmed", "confirmed"]
    evidence: Evidence | None
    confirmed_at: datetime | None


class PageInfo(BaseModel):
    page_no: int
    method: Literal["text", "ocr"]
    quality: float | None
    needs_review: bool


class FileInfo(BaseModel):
    name: str
    size_bytes: int


class VersionRef(BaseModel):
    id: UUID
    version_no: int
    status: VersionStatus
    uploaded_at: datetime


class ContractDetail(ContractSummary):
    file: FileInfo
    job: JobOut | None = Field(description="현재 버전의 가장 최근 작업")
    fields: list[FieldOut]
    pages: list[PageInfo]
    versions: list[VersionRef] = Field(default_factory=list, description="모든 버전 (최신순)")
    previous_values: dict[str, str | None] = Field(
        default_factory=dict, description="바로 이전 버전에서 확인한 값 (수정 계약 비교용)"
    )


class UploadResult(BaseModel):
    contract: ContractDetail
    job: JobOut


class BlockOut(BaseModel):
    key: str
    text: str
    bbox: dict[str, float] | None


class PageText(PageInfo):
    blocks: list[BlockOut]


class ContractText(BaseModel):
    text_version_id: UUID
    kind: Literal["extracted", "user_edited"]
    pages: list[PageText]


class FieldValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_amount: str | None = Field(default=None, pattern=r"^\d{1,14}$")
    final_due_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=200)
    revision_count: str | None = Field(default=None, max_length=50)


class FieldsUpdate(BaseModel):
    """확인값 저장. confirm=true면 필수 항목(금액·납기·지급 조건)을 확정하고 분석 가능 상태로 바꾼다."""

    model_config = ConfigDict(extra="forbid")

    values: FieldValues
    confirm: bool = False


class ContractUpdate(BaseModel):
    """계약서 정보 수정. 직업군은 분석 규칙을 정하므로 계약서마다 고른다."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    job_type: JobType | None = None
