from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import JobType

PortfolioStatus = Literal["draft", "ready", "archived"]
Visibility = Literal["private", "link", "public"]


class AssetRef(BaseModel):
    attachment_id: UUID
    title: str
    url: str | None
    has_file: bool


class QuoteCandidate(BaseModel):
    feedback_id: UUID
    quote: str
    author_name: str


class PortfolioDraft(BaseModel):
    """저장하지 않고 돌려주는 초안. 프리랜서가 고르고 고친 뒤 확정한다."""

    project_id: UUID
    project_completed: bool
    title: str
    description: str | None
    job_type: JobType
    period_start: date | None
    period_end: date | None
    assets: list[AssetRef]
    quote_candidates: list[QuoteCandidate]


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: UUID
    quote: str = Field(min_length=1, max_length=500)
    anonymize: bool = True


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    title: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    period_start: date | None = None
    period_end: date | None = None
    asset_ids: list[UUID] = Field(default_factory=list, max_length=30)
    quotes: list[QuoteIn] = Field(default_factory=list, max_length=10)
    cover_attachment_id: UUID | None = None

    @model_validator(mode="after")
    def _period(self) -> "PortfolioCreate":
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("period_end must be on or after period_start")
        return self


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    period_start: date | None = None
    period_end: date | None = None
    status: PortfolioStatus | None = None
    visibility: Visibility | None = None
    show_client_name: bool | None = None
    # 프리랜서가 "클라이언트에게 피드백 공개 동의를 받았다"를 확인했는지
    feedback_consent: bool | None = None
    cover_attachment_id: UUID | None = None
    asset_ids: list[UUID] | None = Field(default=None, max_length=30)
    quotes: list[QuoteIn] | None = Field(default=None, max_length=10)
    # 읽은 시점의 updated_at. 그 사이 바뀌었으면 409
    version: datetime | None = None


class QuoteOut(BaseModel):
    feedback_id: UUID
    quote: str
    anonymize: bool
    author_name: str


class PortfolioOut(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str | None
    job_type: JobType
    period_start: date | None
    period_end: date | None
    status: PortfolioStatus
    visibility: Visibility
    share_slug: str | None
    show_client_name: bool
    feedback_consent_at: datetime | None
    cover_attachment_id: UUID | None
    client_name: str
    assets: list[AssetRef]
    quotes: list[QuoteOut]
    version: datetime


class PortfolioList(BaseModel):
    items: list[PortfolioOut]


class PublicQuote(BaseModel):
    quote: str
    author: str


class PublicPortfolio(BaseModel):
    title: str
    description: str | None
    job_type: JobType
    period_start: date | None
    period_end: date | None
    freelancer_name: str
    client_name: str | None
    cover_attachment_id: UUID | None
    assets: list[AssetRef]
    quotes: list[PublicQuote]
