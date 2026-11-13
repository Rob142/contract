"""수정 계약 반영 (계약_변경_반영_설계.md 5장)"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import Won
from app.schemas.invoices import PaymentTermIn

StageName = Literal["deposit", "interim", "balance", "other"]


class RevisionDraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version_id: UUID


class VersionInfo(BaseModel):
    id: UUID
    version_no: int
    contract_amount: Won
    due_date: date | None


class InvoiceRef(BaseModel):
    id: UUID
    invoice_no: str | None
    status: Literal["draft", "issued"]
    amount: Won


class OldTerm(BaseModel):
    term_id: UUID
    seq: int
    stage: str
    label: str
    amount: Won
    billed: Won = Field(description="발행된 청구액 (이전 계약에서 이어진 것 포함)")
    drafted: Won = Field(description="초안에 잡힌 금액")
    invoices: list[InvoiceRef]
    must_carry: bool = Field(description="취소되지 않은 청구가 있어 새 단계로 이어 붙여야 한다")


class NewTermDraft(PaymentTermIn):
    key: str


class CarryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_term_id: UUID
    to_key: str = Field(min_length=1, max_length=20)


class RevisionDraft(BaseModel):
    project_id: UUID
    contract_id: UUID
    contract_title: str
    from_version: VersionInfo
    to_version: VersionInfo
    project_version: datetime
    old_terms: list[OldTerm]
    new_terms: list[NewTermDraft]
    proposed_carry: list[CarryIn]
    payment_terms_text: str | None


class NewTermIn(PaymentTermIn):
    key: str = Field(min_length=1, max_length=20)


class RevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version_id: UUID
    version: datetime | None = Field(default=None, description="프로젝트 version (낙관적 잠금)")
    contract_amount: Won
    due_date: date | None = None
    payment_terms: list[NewTermIn] = Field(min_length=1, max_length=10)
    carry: list[CarryIn] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _validate(self) -> "RevisionIn":
        keys = [t.key for t in self.payment_terms]
        if len(set(keys)) != len(keys):
            raise ValueError("payment term keys must be unique")
        sources = [c.from_term_id for c in self.carry]
        if len(set(sources)) != len(sources):
            raise ValueError("each previous payment term can be carried only once")
        if any(c.to_key not in keys for c in self.carry):
            raise ValueError("carry target must be one of payment_terms")
        if sum((t.amount for t in self.payment_terms), Decimal(0)) != self.contract_amount:
            raise ValueError("payment terms must add up to the contract amount")
        return self
