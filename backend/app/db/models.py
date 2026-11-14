"""ORM 매핑. 스키마의 원본은 alembic/sql 이며, 여기서는 쓰는 테이블만 매핑한다.

기본값(id, created_at)과 updated_at 트리거는 DB가 채운다.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import FetchedValue, ForeignKey, Numeric, Text, column, func, table
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    __mapper_args__ = {"eager_defaults": True}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), server_onupdate=FetchedValue())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    job_type: Mapped[str] = mapped_column(Text)
    default_llm_mode: Mapped[str] = mapped_column(Text, server_default="ask")
    commercial_llm_model: Mapped[str | None] = mapped_column(Text)
    commercial_llm_api_key: Mapped[str | None] = mapped_column(Text)
    commercial_llm_api_base: Mapped[str | None] = mapped_column(Text)
    local_llm_model: Mapped[str | None] = mapped_column(Text)
    local_llm_api_base: Mapped[str | None] = mapped_column(Text)
    local_llm_api_key: Mapped[str | None] = mapped_column(Text)
    llm_models: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    issuer_name: Mapped[str | None] = mapped_column(Text)
    issuer_display_name: Mapped[str | None] = mapped_column(Text)
    issuer_contact: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    bank_account: Mapped[str | None] = mapped_column(Text)
    terms_agreed_at: Mapped[datetime]

    @property
    def has_commercial_llm_api_key(self) -> bool:
        return bool(self.commercial_llm_api_key)

    @property
    def has_local_llm_api_key(self) -> bool:
        return bool(self.local_llm_api_key)

    @property
    def llm_models_public(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in self.llm_models or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "id": str(item.get("id") or ""),
                    "mode": "local" if item.get("mode") == "local" else "commercial",
                    "model": str(item.get("model") or ""),
                    "api_base": item.get("api_base") or None,
                    "has_api_key": bool(item.get("api_key")),
                    "is_active": bool(item.get("is_active")),
                }
            )
        return out


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID]
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    response_status: Mapped[int | None]
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Client(TimestampMixin, Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # (client_id, owner_id)·(contract_version_id, owner_id) 복합 FK는 DB가 강제한다
    client_id: Mapped[uuid.UUID]
    contract_version_id: Mapped[uuid.UUID | None]
    name: Mapped[str] = mapped_column(Text)
    job_type: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date | None]
    due_date: Mapped[date | None]
    contract_amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), server_default="0")
    currency: Mapped[str] = mapped_column(Text, server_default="KRW")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    included_revisions: Mapped[int | None]


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="todo")
    position: Mapped[int] = mapped_column(server_default="0")
    due_date: Mapped[date | None]
    completed_at: Mapped[datetime | None]
    hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    hourly_rate: Mapped[Decimal | None] = mapped_column(Numeric(14, 0))
    source: Mapped[str] = mapped_column(Text, server_default="manual")
    source_note: Mapped[str | None] = mapped_column(Text)

    checklist: Mapped[list["TaskChecklistItem"]] = relationship(
        order_by="TaskChecklistItem.position", lazy="selectin", cascade="all, delete-orphan"
    )


class TaskChecklistItem(TimestampMixin, Base):
    __tablename__ = "task_checklist_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)
    is_done: Mapped[bool] = mapped_column(server_default="false")
    position: Mapped[int] = mapped_column(server_default="0")


class PaymentTerm(TimestampMixin, Base):
    __tablename__ = "payment_terms"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_version_id: Mapped[uuid.UUID]
    seq: Mapped[int]
    stage: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    requirement: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date | None]
    confirmed_by: Mapped[uuid.UUID | None]
    confirmed_at: Mapped[datetime | None]


class PaymentTermSuccession(Base):
    """청구가 있던 옛 지급 단계 → 수정 계약의 새 단계 (추가만 한다, 0005)"""

    __tablename__ = "payment_term_successions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID]
    project_id: Mapped[uuid.UUID]
    predecessor_term_id: Mapped[uuid.UUID]
    successor_term_id: Mapped[uuid.UUID]
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# 읽기 전용 뷰 (alembic/sql/03_views.sql)
v_project_summary = table(
    "v_project_summary",
    column("project_id"),
    column("total_tasks"),
    column("done_tasks"),
    column("progress_pct"),
    column("billed_amount"),
    column("paid_amount"),
    column("outstanding_amount"),
)

v_invoice_balances = table(
    "v_invoice_balances",
    column("invoice_id"),
    column("owner_id"),
    column("project_id"),
    column("invoice_no"),
    column("status"),
    column("due_date"),
    column("total"),
    column("paid_amount"),
    column("balance"),
    column("payment_status"),
    column("is_overdue"),
)


class StoredFile(TimestampMixin, Base):
    __tablename__ = "files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    storage_kind: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str] = mapped_column(Text)
    deleted_at: Mapped[datetime | None]


class Contract(TimestampMixin, Base):
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(Text)
    job_type: Mapped[str] = mapped_column(Text)


class ContractVersion(TimestampMixin, Base):
    __tablename__ = "contract_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID]
    version_no: Mapped[int]
    file_id: Mapped[uuid.UUID]
    sha256: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, server_default="uploaded")
    failure_reason: Mapped[str | None] = mapped_column(Text)


class ContractPage(TimestampMixin, Base):
    __tablename__ = "contract_pages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contract_versions.id", ondelete="CASCADE")
    )
    page_no: Mapped[int]
    extraction_method: Mapped[str] = mapped_column(Text)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    needs_review: Mapped[bool] = mapped_column(server_default="false")


class ContractTextVersion(Base):
    __tablename__ = "contract_text_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contract_versions.id", ondelete="CASCADE")
    )
    version_no: Mapped[int]
    kind: Mapped[str] = mapped_column(Text)
    based_on_id: Mapped[uuid.UUID | None]
    edited_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ContractTextBlock(Base):
    __tablename__ = "contract_text_blocks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    text_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contract_text_versions.id", ondelete="CASCADE")
    )
    page_no: Mapped[int]
    block_key: Mapped[str] = mapped_column(Text)
    position: Mapped[int]
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)


class ContractField(TimestampMixin, Base):
    __tablename__ = "contract_fields"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    contract_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contract_versions.id", ondelete="CASCADE")
    )
    field_key: Mapped[str] = mapped_column(Text)
    extracted_value: Mapped[str | None] = mapped_column(Text)
    confirmed_value: Mapped[str | None] = mapped_column(Text)
    evidence_block_id: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(Text, server_default="unconfirmed")
    confirmed_by: Mapped[uuid.UUID | None]
    confirmed_at: Mapped[datetime | None]


class AnalysisJob(TimestampMixin, Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    contract_version_id: Mapped[uuid.UUID]
    text_version_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    stage: Mapped[str | None] = mapped_column(Text)
    job_type: Mapped[str | None] = mapped_column(Text)
    llm_mode: Mapped[str | None] = mapped_column(Text)
    model_config_: Mapped[dict[str, Any]] = mapped_column("model_config", JSONB, default=dict)
    rules_version: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    reuse_key: Mapped[str | None] = mapped_column(Text)
    external_send_consented_at: Mapped[datetime | None]
    run_id: Mapped[uuid.UUID | None]
    attempts: Mapped[int] = mapped_column(server_default="0")
    max_attempts: Mapped[int] = mapped_column(server_default="3")
    heartbeat_at: Mapped[datetime | None]
    lease_expires_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class Invoice(TimestampMixin, Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID]
    invoice_no: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    title: Mapped[str] = mapped_column(Text)
    issue_date: Mapped[date | None]
    due_date: Mapped[date | None]
    currency: Mapped[str] = mapped_column(Text, server_default="KRW")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 0), server_default="0")
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), server_default="0")
    withholding_amount: Mapped[Decimal] = mapped_column(Numeric(14, 0), server_default="0")
    adjustment_note: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 0), server_default="0")
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    replaces_invoice_id: Mapped[uuid.UUID | None]
    issued_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list["InvoiceItem"]] = relationship(
        order_by="InvoiceItem.position", lazy="selectin", cascade="all, delete-orphan"
    )


class InvoiceItem(TimestampMixin, Base):
    __tablename__ = "invoice_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(server_default="0")
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), server_default="1")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    basis_note: Mapped[str | None] = mapped_column(Text)
    basis_confirmed_at: Mapped[datetime | None]

    allocations: Mapped[list["BillingAllocation"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan"
    )


class BillingAllocation(Base):
    __tablename__ = "billing_allocations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoice_items.id", ondelete="CASCADE"))
    payment_term_id: Mapped[uuid.UUID | None]
    task_id: Mapped[uuid.UUID | None]
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))
    paid_on: Mapped[date]
    method: Mapped[str] = mapped_column(Text, server_default="bank_transfer")
    memo: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID]
    voided_at: Mapped[datetime | None]
    void_reason: Mapped[str | None] = mapped_column(Text)


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(Text)
    rule_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    review_level: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    user_action: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    validation_status: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Attachment(TimestampMixin, Base):
    __tablename__ = "attachments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id"))
    url: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None]
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 0))
    memo: Mapped[str | None] = mapped_column(Text)


class ShareLink(TimestampMixin, Base):
    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    show_invoices: Mapped[bool] = mapped_column(server_default="false")
    allow_feedback: Mapped[bool] = mapped_column(server_default="true")
    last_viewed_at: Mapped[datetime | None]


class TaskFeedback(Base):
    __tablename__ = "task_feedback"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    author_role: Mapped[str] = mapped_column(Text)
    author_name: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ViewEvent(Base):
    __tablename__ = "view_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    share_link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("share_links.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    viewer_name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RevisionRequest(Base):
    __tablename__ = "revision_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    seq: Mapped[int]
    body: Mapped[str] = mapped_column(Text)
    requester_name: Mapped[str] = mapped_column(Text)
    over_limit: Mapped[bool] = mapped_column(server_default="false")
    excluded_at: Mapped[datetime | None]
    excluded_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ExtraQuote(TimestampMixin, Base):
    __tablename__ = "extra_quotes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    revision_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("revision_requests.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 0))


class PortfolioItem(TimestampMixin, Base):
    __tablename__ = "portfolio_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    job_type: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date | None]
    period_end: Mapped[date | None]
    cover_attachment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("attachments.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    visibility: Mapped[str] = mapped_column(Text, server_default="private")
    share_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    show_client_name: Mapped[bool] = mapped_column(server_default="false")
    feedback_consent_at: Mapped[datetime | None]


class PortfolioAsset(Base):
    __tablename__ = "portfolio_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio_items.id", ondelete="CASCADE"))
    attachment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attachments.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(server_default="0")


class PortfolioQuote(Base):
    __tablename__ = "portfolio_quotes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio_items.id", ondelete="CASCADE"))
    feedback_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("task_feedback.id", ondelete="CASCADE"))
    quote: Mapped[str] = mapped_column(Text)
    anonymize: Mapped[bool] = mapped_column(server_default="true")
