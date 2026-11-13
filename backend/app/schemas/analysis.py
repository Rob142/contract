from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import JobType
from app.schemas.contracts import JobOut


class ModeStatus(BaseModel):
    available: bool
    provider: str | None
    model: str | None


class LlmStatus(BaseModel):
    commercial: ModeStatus
    local: ModeStatus


class LlmTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["commercial", "local"] = "commercial"
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    api_base: str | None = Field(default=None, max_length=500)


class LlmTestOut(BaseModel):
    ok: bool
    provider: str
    model_id: str
    message: str


class AnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_mode: Literal["commercial", "local"]
    job_type: JobType | None = None
    # 상용 모델은 외부 전송 내용을 확인했다는 동의가 있어야 실행한다 (설계서 4장)
    consent_external: bool = False
    # 같은 조건의 이전 결과가 있어도 다시 분석
    force: bool = False


class AnalyzeOut(BaseModel):
    job: JobOut
    reused: bool = Field(description="같은 텍스트·규칙·모델로 이미 분석한 결과를 다시 썼는지")


class EvidenceOut(BaseModel):
    block_key: str
    page_no: int
    quote: str
    valid: bool


class ResultOut(BaseModel):
    id: UUID
    rule_id: str
    rule_title: str
    importance: str
    status: Literal["found", "not_found", "unclear"]
    review_level: Literal["caution", "needs_check", "confirmed"]
    risk_level: str | None
    title: str
    explanation: str
    user_action: str | None
    suggestion: str | None
    evidence: list[EvidenceOut]
    validation_status: Literal["pending", "passed", "failed"]


class AnalysisCounts(BaseModel):
    total: int
    caution: int
    needs_check: int
    confirmed: int


class AnalysisOut(BaseModel):
    job_id: UUID
    analyzed_at: datetime | None
    llm_mode: str | None
    provider: str | None
    model_id: str | None
    job_type: JobType
    rules_version: str | None
    prompt_version: str | None
    counts: AnalysisCounts
    results: list[ResultOut]


class AnalysisView(BaseModel):
    analysis: AnalysisOut | None = Field(description="현재 버전의 가장 최근 성공한 분석")
    latest_job: JobOut | None = Field(description="가장 최근 분석 작업 (진행 중·실패 포함)")


class RevisionPromptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_ids: list[UUID] = Field(min_length=1, max_length=20)


class RevisionPromptOut(BaseModel):
    prompt: str
    result_count: int
