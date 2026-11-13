"""LLM 호출 경계 (설계서 4·5장).

상용 API와 로컬 추론을 같은 인터페이스로 부른다. 실행 방식은 사용자가 고르고,
로컬 모드는 어떤 경우에도 외부 API로 자동 전환하지 않는다 (get_provider가 mode별로만 고른다).
API 키는 서버 설정 또는 사용자 설정에서만 읽고 작업 테이블·로그·응답에 남기지 않는다.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.core.config import get_settings

Mode = Literal["commercial", "local"]


@dataclass(frozen=True)
class LlmResult:
    data: dict[str, Any]
    model_id: str
    input_tokens: int | None
    output_tokens: int | None


class LlmUnavailableError(Exception):
    """설정되지 않았거나 쓸 수 없는 실행 방식."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LlmTransientError(Exception):
    """잠시 뒤 다시 시도하면 될 수 있는 오류 (429, 5xx, 시간 초과, 연결)."""


class LlmOutputError(Exception):
    """모델이 응답했지만 쓸 수 없는 결과 (차단, 길이 초과, 형식 오류). 같은 입력으로는 재시도하지 않는다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class LlmProvider(Protocol):
    provider: str
    model_id: str

    def generate_json(
        self, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LlmResult: ...


class LiteLlmProvider:
    """LiteLLM으로 상용(OpenAI, Gemini, Anthropic 등) 및 로컬(Ollama, vLLM 등) 모델을 부른다."""

    def __init__(
        self,
        model_id: str,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout_seconds: int = 180,
        provider_name: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.api_key = api_key
        self.api_base = api_base
        self.timeout_seconds = timeout_seconds
        if provider_name:
            self.provider = provider_name
        elif "/" in model_id:
            self.provider = model_id.split("/", 1)[0]
        else:
            self.provider = "litellm"

    def generate_json(
        self, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LlmResult:
        import litellm
        from litellm import exceptions as litellm_exc

        schema_instruction = (
            "\n\n반드시 순수 JSON 객체(dict)만 출력하세요. 마크다운 코드블록 없이 JSON만 반환해야 하며, "
            f"다음 JSON 스키마를 따르세요:\n{json.dumps(schema, ensure_ascii=False)}"
        )
        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": system + schema_instruction},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_output_tokens,
            "timeout": self.timeout_seconds,
            "num_retries": 1,
            "response_format": {"type": "json_object"},
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        try:
            try:
                response = litellm.completion(**kwargs)
            except litellm_exc.BadRequestError as exc:
                # 일부 로컬/구형 모델이 response_format={"type": "json_object"}를 지원하지 않는 경우 폴백
                if "response_format" in str(exc).lower() or "json_object" in str(exc).lower():
                    kwargs.pop("response_format", None)
                    response = litellm.completion(**kwargs)
                else:
                    raise
        except (litellm_exc.AuthenticationError, litellm_exc.PermissionDeniedError) as exc:
            raise LlmUnavailableError("llm_auth_failed", "the API key was rejected") from exc
        except litellm_exc.RateLimitError as exc:
            raise LlmTransientError("rate limited") from exc
        except (
            litellm_exc.APIConnectionError,
            litellm_exc.ServiceUnavailableError,
            litellm_exc.Timeout,
            litellm_exc.InternalServerError,
            TimeoutError,
            OSError,
        ) as exc:
            raise LlmTransientError(type(exc).__name__) from exc
        except litellm_exc.ContentPolicyViolationError as exc:
            raise LlmOutputError("llm_blocked", "prompt blocked by content policy") from exc
        except litellm_exc.BadRequestError as exc:
            raise LlmOutputError("llm_request_rejected", f"request rejected: {exc}") from exc
        except Exception as exc:
            raise LlmTransientError(type(exc).__name__) from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LlmOutputError("llm_blocked", "empty choices in response")
        choice = choices[0]
        finish = getattr(choice, "finish_reason", None)
        if finish == "length":
            raise LlmOutputError("llm_truncated", "the response hit the output limit")
        if finish in ("content_filter", "safety"):
            raise LlmOutputError("llm_blocked", f"response stopped: {finish}")

        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message else None
        usage = getattr(response, "usage", None)
        return LlmResult(
            data=parse_json_object(content or ""),
            model_id=getattr(response, "model", None) or self.model_id,
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=getattr(usage, "completion_tokens", None) if usage else None,
        )


class GeminiProvider:
    """Google Gen AI SDK (google-genai)로 Gemini를 부른다. JSON 스키마로 출력 형식을 고정한다."""

    provider = "gemini"

    def __init__(self, api_key: str, model_id: str, timeout_seconds: int) -> None:
        from google import genai
        from google.genai import types

        self.model_id = model_id
        self._types = types
        # 재시도는 작업자 쪽에서 시도 횟수로 관리하므로 SDK 재시도는 한 번만
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                # 시스템 지시(system_instruction)는 v1beta에서만 받는다 (v1로 보내면 400)
                api_version="v1beta",
                timeout=timeout_seconds * 1000,
                retry_options=types.HttpRetryOptions(attempts=2),
            ),
        )

    def generate_json(
        self, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LlmResult:
        from google.genai import errors

        types = self._types
        try:
            response = self._client.models.generate_content(
                model=self.model_id,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    temperature=0.1,
                    max_output_tokens=max_output_tokens,
                ),
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                raise LlmTransientError("rate limited") from exc
            if exc.code in (401, 403):
                raise LlmUnavailableError("llm_auth_failed", "the API key was rejected") from exc
            raise LlmOutputError("llm_request_rejected", f"request rejected ({exc.code})") from exc
        except errors.ServerError as exc:
            raise LlmTransientError(f"server error ({exc.code})") from exc
        except errors.APIError as exc:
            raise LlmTransientError(f"api error ({exc.code})") from exc
        except (TimeoutError, OSError) as exc:  # 네트워크·시간 초과
            raise LlmTransientError(type(exc).__name__) from exc

        feedback = response.prompt_feedback
        if feedback is not None and feedback.block_reason:
            raise LlmOutputError("llm_blocked", f"prompt blocked: {feedback.block_reason}")
        candidate = response.candidates[0] if response.candidates else None
        finish = candidate.finish_reason.name if candidate and candidate.finish_reason else None
        if finish == "MAX_TOKENS":
            raise LlmOutputError("llm_truncated", "the response hit the output limit")
        if finish not in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
            raise LlmOutputError("llm_blocked", f"response stopped: {finish}")

        usage = response.usage_metadata
        return LlmResult(
            data=parse_json_object(response.text or ""),
            model_id=response.model_version or self.model_id,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # 텍스트 앞뒤에 설명이 붙은 경우 첫 번째 { ... } 구간을 추출해 재시도한다
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise LlmOutputError("llm_invalid_json", "the model did not return valid JSON") from exc
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc2:
            raise LlmOutputError("llm_invalid_json", "the model did not return valid JSON") from exc2
    if not isinstance(value, dict):
        raise LlmOutputError("llm_invalid_json", "the model did not return a JSON object")
    return value


class FakeProvider:
    """테스트·화면 확인용 가짜 모델. 외부로 아무것도 보내지 않는다.

    규칙의 키워드가 있는 줄을 근거로 '발견', 없으면 '미발견'을 낸다.
    입력 문서의 [블록키] 형식을 그대로 읽어 실제 모델과 같은 검증 경로를 탄다.
    """

    provider = "fake"
    model_id = "fake-contract-reviewer"

    def generate_json(
        self, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LlmResult:
        from app.analysis.rules import BY_JOB, COMMON

        rules = {r.id: r for r in COMMON + tuple(r for group in BY_JOB.values() for r in group)}
        lines = re.findall(r"^\[(p\d+-b\d+)\] (.*)$", user, flags=re.M)
        wanted = re.findall(r"^- ([A-Z]{3}-\d{3}) ", system, flags=re.M)
        results = []
        for rule_id in wanted:
            rule = rules[rule_id]
            hit = next(((k, t) for k, t in lines if any(word in t for word in rule.keywords)), None)
            results.append(
                {
                    "rule_id": rule_id,
                    "status": "found" if hit else "not_found",
                    "risk_level": "low" if hit else ("high" if rule.importance == "high" else "medium"),
                    "title": f"{rule.title}이(가) {'확인됐어요' if hit else '명시되지 않았어요'}",
                    "explanation": f"{rule.check}을(를) "
                    + ("원문에서 확인했어요." if hit else "제공된 문서에서 찾지 못했어요."),
                    "user_action": "" if hit else f"{rule.title}을(를) 거래처와 협의해 보세요.",
                    "suggestion": "" if hit else rule.direction,
                    "evidence": [{"block_key": hit[0], "quote": hit[1]}] if hit else [],
                }
            )
        return LlmResult(
            data={"results": results}, model_id=self.model_id, input_tokens=None, output_tokens=None
        )


def _normalize_commercial_model(model: str, api_base: str | None = None) -> tuple[str, str]:
    """LiteLLM 모델 문자열과 표시용 provider 이름을 반환한다."""
    m = model.strip()
    if "/" in m:
        return m, m.split("/", 1)[0]
    if m.startswith("gemini"):
        return f"gemini/{m}", "gemini"
    if m.startswith("claude"):
        return f"anthropic/{m}", "anthropic"
    if m.startswith(("gpt-", "o1", "o3", "o4")):
        return f"openai/{m}", "openai"
    if api_base:
        return f"openai/{m}", "openai"
    return f"openai/{m}", "openai"


def _normalize_local_model(model: str, api_base: str | None) -> tuple[str, str]:
    """로컬 추론 서버용 LiteLLM 모델 문자열과 provider 이름을 반환한다."""
    m = model.strip()
    if "/" in m:
        return m, m.split("/", 1)[0]
    if api_base and "/v1" in api_base:
        return f"openai/{m}", "openai"
    return f"ollama_chat/{m}", "ollama"


def _active_entry(user: Any | None, mode: Mode) -> tuple[str | None, str | None, str | None]:
    """사용자의 llm_models 목록 또는 단일 필드에서 (model, api_key, api_base)를 꺼낸다."""
    if user is None:
        return None, None, None
    models = getattr(user, "llm_models", None) or []
    mode_items = [m for m in models if isinstance(m, dict) and m.get("mode") == mode]
    if mode_items:
        active = next((m for m in mode_items if m.get("is_active")), mode_items[0])
        return active.get("model"), active.get("api_key"), active.get("api_base")
    if mode == "commercial":
        return (
            getattr(user, "commercial_llm_model", None),
            getattr(user, "commercial_llm_api_key", None),
            getattr(user, "commercial_llm_api_base", None),
        )
    return (
        getattr(user, "local_llm_model", None),
        getattr(user, "local_llm_api_key", None),
        getattr(user, "local_llm_api_base", None),
    )


def provider_status(user: Any | None = None) -> dict[str, dict[str, Any]]:
    """화면에 보여줄 실행 방식별 사용 가능 여부 (키 값은 절대 내보내지 않는다)."""
    s = get_settings()

    # 1. 상용(commercial) 상태 계산
    user_c_model, user_c_key, user_c_base = _active_entry(user, "commercial")

    if user_c_model == "fake":
        commercial_status = {"available": True, "provider": "fake", "model": FakeProvider.model_id}
    elif user_c_model or user_c_key or user_c_base:
        raw_model = user_c_model or s.gemini_model
        _, prov = _normalize_commercial_model(raw_model, user_c_base)
        effective_key = (
            user_c_key
            or (s.gemini_api_key if prov == "gemini" else None)
            or ("custom" if user_c_base else None)
        )
        commercial_status = {
            "available": bool(effective_key and raw_model),
            "provider": prov,
            "model": raw_model,
        }
    else:
        commercial_ready = s.llm_commercial_provider == "fake" or bool(s.gemini_api_key)
        commercial_status = {
            "available": commercial_ready,
            "provider": s.llm_commercial_provider,
            "model": FakeProvider.model_id if s.llm_commercial_provider == "fake" else s.gemini_model,
        }

    # 2. 로컬(local) 상태 계산
    user_l_model, _, user_l_base = _active_entry(user, "local")
    local_model = user_l_model or s.local_llm_model
    local_base = user_l_base or s.local_llm_api_base
    if local_model:
        _, local_prov = _normalize_local_model(local_model, local_base)
        local_status: dict[str, Any] = {
            "available": True,
            "provider": local_prov,
            "model": local_model,
        }
    else:
        local_status = {"available": False, "provider": None, "model": None}

    return {
        "commercial": commercial_status,
        "local": local_status,
    }


def get_provider(mode: Mode, user: Any | None = None) -> LlmProvider:
    s = get_settings()
    if mode == "local":
        user_l_model, user_l_key, user_l_base = _active_entry(user, "local")
        local_model = user_l_model or s.local_llm_model
        local_base = user_l_base or s.local_llm_api_base
        local_key = user_l_key or s.local_llm_api_key
        if not local_model:
            # 로컬 추론 서버는 아직 연결 전. 외부 API로 대신 보내지 않는다.
            raise LlmUnavailableError("local_llm_not_configured", "no local inference server is configured")
        if local_model == "fake":
            return FakeProvider()
        norm_model, prov = _normalize_local_model(local_model, local_base)
        return LiteLlmProvider(
            model_id=norm_model,
            api_key=local_key or "local",
            api_base=local_base,
            timeout_seconds=s.llm_timeout_seconds,
            provider_name=prov,
        )

    # commercial 모드
    user_c_model, user_c_key, user_c_base = _active_entry(user, "commercial")

    if user_c_model == "fake":
        return FakeProvider()
    if user_c_model or user_c_key or user_c_base:
        raw_model = user_c_model or s.gemini_model
        norm_model, prov = _normalize_commercial_model(raw_model, user_c_base)
        effective_key = (
            user_c_key
            or (s.gemini_api_key if prov == "gemini" else None)
            or ("custom" if user_c_base else None)
        )
        if not effective_key:
            raise LlmUnavailableError("llm_not_configured", "the commercial LLM API key is not set")
        return LiteLlmProvider(
            model_id=norm_model,
            api_key=effective_key,
            api_base=user_c_base,
            timeout_seconds=s.llm_timeout_seconds,
            provider_name=prov,
        )

    if s.llm_commercial_provider == "fake":
        return FakeProvider()
    if s.llm_commercial_provider == "gemini":
        if not s.gemini_api_key:
            raise LlmUnavailableError("llm_not_configured", "the Gemini API key is not set")
        return GeminiProvider(s.gemini_api_key, s.gemini_model, s.llm_timeout_seconds)
    if s.llm_commercial_provider == "litellm":
        if not s.gemini_api_key:
            raise LlmUnavailableError("llm_not_configured", "the API key is not set")
        norm_model, prov = _normalize_commercial_model(s.gemini_model)
        return LiteLlmProvider(
            model_id=norm_model,
            api_key=s.gemini_api_key,
            timeout_seconds=s.llm_timeout_seconds,
            provider_name=prov,
        )
    raise LlmUnavailableError("llm_not_configured", f"unknown provider {s.llm_commercial_provider}")
