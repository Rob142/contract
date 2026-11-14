from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import Won


class MonthlyIncome(BaseModel):
    month: str  # YYYY-MM
    received: Won  # 입금일 기준 입금액 = 수입 (취소된 입금 제외)
    billed: Won  # 발행월 기준 청구액 (참고)


class MonthlyIncomeOut(BaseModel):
    months: list[MonthlyIncome]
    received_total: Won
    billed_total: Won


class MonthProject(BaseModel):
    project_id: UUID
    name: str
    received: Won


class MonthDetail(BaseModel):
    month: str
    received: Won
    projects: list[MonthProject]


class EvidenceDoc(BaseModel):
    id: UUID
    project_id: UUID
    project_name: str
    title: str
    doc_type: str | None
    issued_on: date | None
    amount: Won | None
    url: str | None
    has_file: bool
