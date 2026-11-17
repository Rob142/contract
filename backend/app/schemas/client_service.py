"""Validated client-service inputs; money is always integer KRW Decimal."""

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator

from app.schemas.common import JobType, Won

Role = Literal["owner", "admin", "member", "viewer"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkspaceIn(Input):
    name: str = Field(min_length=1, max_length=100)


class InviteIn(Input):
    email: EmailStr
    role: Literal["admin", "member", "viewer"] = "member"
    send_email: bool = False


class AcceptIn(Input):
    token: str = Field(min_length=20, max_length=200)
    workspace_id: UUID | None = None


class MemberIn(Input):
    role: Role


class ProjectMemberIn(Input):
    user_id: UUID
    can_finance: bool = False
    approver: bool = False


class PublicationIn(Input):
    task_ids: list[UUID] = Field(max_length=200)


class DeliveryIn(Input):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=5000)
    attachment_ids: list[UUID] = Field(min_length=1, max_length=30)
    due_date: date | None = None
    delivery_id: UUID | None = None


class ReviewIn(Input):
    kind: Literal["comment", "seen", "changes", "approved"]
    body: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def text_required(self) -> Self:
        if self.kind in ("comment", "changes") and not self.body:
            raise ValueError("의견 또는 수정 요청 내용을 입력하세요")
        return self


class PortfolioWork(Input):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=2000)
    contribution: str = Field(min_length=1, max_length=1000)
    url: HttpUrl
    image_url: HttpUrl | None = None
    client_name: str = Field(default="", max_length=100)
    feedback: str = Field(default="", max_length=1000)
    assets_consent: bool = False
    client_name_consent: bool = False
    feedback_consent: bool = False

    @model_validator(mode="after")
    def consent(self) -> Self:
        if not self.assets_consent:
            raise ValueError("공개 가능한 작업만 등록하세요")
        if self.client_name and not self.client_name_consent:
            raise ValueError("고객 이름 공개 동의가 필요합니다")
        if self.feedback and not self.feedback_consent:
            raise ValueError("피드백 공개 동의가 필요합니다")
        return self


class ProfileIn(Input):
    published: bool = False
    headline: str = Field(min_length=1, max_length=150)
    bio: str = Field(default="", max_length=3000)
    job_type: JobType
    services: list[str] = Field(min_length=1, max_length=20)
    scope: str = Field(min_length=1, max_length=2000)
    price: Won | None = None
    price_type: Literal["fixed", "from", "quote"] = "quote"
    vat: Literal["excluded", "included", "not_applicable"] = "excluded"
    exclusions: str = Field(default="", max_length=1000)
    revisions: int = Field(default=0, ge=0, le=99)
    days: int | None = Field(default=None, ge=1, le=365)
    available_from: date | None = None
    originals: str = Field(default="별도 협의", max_length=300)
    rights: str = Field(default="별도 협의", max_length=500)
    portfolio: list[PortfolioWork] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def priced(self) -> Self:
        if self.price_type != "quote" and self.price is None:
            raise ValueError("가격을 입력하세요")
        self.services = [s.strip() for s in self.services if s.strip()]
        if not self.services or any(len(s) > 80 for s in self.services):
            raise ValueError("제공 업무를 입력하세요 (항목당 80자 이하)")
        return self


class InquiryIn(Input):
    freelancer_id: UUID
    title: str = Field(min_length=1, max_length=150)
    purpose: str = Field(min_length=1, max_length=3000)
    scope: str = Field(min_length=1, max_length=3000)
    deliverables: str = Field(min_length=1, max_length=2000)
    budget: Won | None = None
    due_date: date | None = None
    references: str = Field(default="", max_length=3000)
    send: bool = False


class QuoteIn(Input):
    amount: Won
    vat: Literal["excluded", "included", "not_applicable"]
    scope: str = Field(min_length=1, max_length=3000)
    deliverables: str = Field(min_length=1, max_length=2000)
    exclusions: str = Field(min_length=1, max_length=1000)
    revisions: int = Field(ge=0, le=99)
    due_date: date
    client_due_date: date
    payment: str = Field(min_length=1, max_length=2000)
    rights: str = Field(min_length=1, max_length=1000)
    originals: str = Field(min_length=1, max_length=1000)


class MessageIn(Input):
    body: str = Field(min_length=1, max_length=5000)


class ProjectMessageIn(MessageIn):
    session_id: UUID | None = None


class ChatActionIn(Input):
    action: Literal["accept", "decline", "close"]
