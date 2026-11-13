from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

JobType = Literal["dev", "design", "video", "marketing"]
LlmMode = Literal["ask", "commercial", "local"]


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    job_type: JobType
    agree_terms: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    remember: bool = False


class LlmModelOut(BaseModel):
    id: str
    mode: Literal["commercial", "local"]
    model: str
    api_base: str | None = None
    has_api_key: bool = False
    is_active: bool = False


class LlmModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["commercial", "local"] = "commercial"
    model: str = Field(min_length=1, max_length=200)
    api_base: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str
    job_type: JobType
    default_llm_mode: LlmMode
    commercial_llm_model: str | None = None
    commercial_llm_api_base: str | None = None
    has_commercial_llm_api_key: bool = False
    local_llm_model: str | None = None
    local_llm_api_base: str | None = None
    has_local_llm_api_key: bool = False
    llm_models: list[LlmModelOut] = Field(default_factory=list, validation_alias="llm_models_public")
    issuer_name: str | None
    issuer_display_name: str | None
    issuer_contact: str | None
    bank_name: str | None
    bank_account: str | None


class UserUpdate(BaseModel):
    """내 정보와 설정. 이메일 변경은 확인 절차가 필요해 MVP에서 제외한다."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=50)
    job_type: JobType | None = None
    default_llm_mode: LlmMode | None = None
    commercial_llm_model: str | None = Field(default=None, max_length=200)
    commercial_llm_api_key: str | None = Field(default=None, max_length=500)
    commercial_llm_api_base: str | None = Field(default=None, max_length=500)
    local_llm_model: str | None = Field(default=None, max_length=200)
    local_llm_api_base: str | None = Field(default=None, max_length=500)
    local_llm_api_key: str | None = Field(default=None, max_length=500)
    issuer_name: str | None = Field(default=None, max_length=100)
    issuer_display_name: str | None = Field(default=None, max_length=100)
    issuer_contact: str | None = Field(default=None, max_length=200)
    bank_name: str | None = Field(default=None, max_length=50)
    bank_account: str | None = Field(default=None, max_length=100)


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
