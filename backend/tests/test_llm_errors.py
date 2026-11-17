"""LiteLLM 호출: 모델이 거부하는 선택 인자는 빼고 다시 부르고, 실패 원인은 code로 구분한다."""

from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from fastapi.testclient import TestClient
from litellm import exceptions as E

from app.analysis.llm import (
    LiteLlmProvider,
    LlmOutputError,
    LlmTransientError,
    LlmUnavailableError,
)
from tests.conftest import register

API = "/api/v1"
SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}


def ok_response() -> Any:
    message = SimpleNamespace(content='{"status": "ok"}')
    choice = SimpleNamespace(finish_reason="stop", message=message)
    return SimpleNamespace(
        choices=[choice],
        model="gemini-3.8-flash",
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


def provider() -> LiteLlmProvider:
    return LiteLlmProvider(model_id="gemini/gemini-3.8-flash", api_key="k", timeout_seconds=5)


def script(monkeypatch: pytest.MonkeyPatch, outcomes: list[Exception | Any]) -> list[dict[str, Any]]:
    """litellm.completion이 outcomes를 차례로 돌려주거나 던지게 하고, 받은 인자를 기록한다."""
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> Any:
        calls.append(dict(kwargs))
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(litellm, "completion", fake)
    return calls


def unsupported(param: str) -> E.UnsupportedParamsError:
    return E.UnsupportedParamsError(
        message=f"gemini does not support parameters: ['{param}'], for model=gemini-3.8-flash.",
        llm_provider="gemini",
        model="gemini-3.8-flash",
    )


def test_temperature_is_dropped_when_model_rejects_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = script(monkeypatch, [unsupported("temperature"), ok_response()])
    res = provider().generate_json("sys", "ping", SCHEMA, max_output_tokens=64)
    assert res.data == {"status": "ok"}
    assert "temperature" in calls[0] and "temperature" not in calls[1]
    assert "response_format" in calls[1]  # 받아 주는 인자는 그대로 둔다


def test_each_rejected_param_is_dropped_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = script(monkeypatch, [unsupported("response_format"), unsupported("temperature"), ok_response()])
    provider().generate_json("sys", "ping", SCHEMA, max_output_tokens=64)
    assert len(calls) == 3
    assert "response_format" not in calls[1] and "temperature" in calls[1]
    assert "response_format" not in calls[2] and "temperature" not in calls[2]


def test_unrelated_bad_request_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = E.BadRequestError(message="messages must not be empty", model="m", llm_provider="gemini")
    calls = script(monkeypatch, [bad])
    with pytest.raises(LlmOutputError) as caught:
        provider().generate_json("sys", "ping", SCHEMA, max_output_tokens=64)
    assert caught.value.code == "llm_request_rejected"
    assert "messages must not be empty" in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("error", "expected_type", "code"),
    [
        (
            E.AuthenticationError(message="bad key", llm_provider="gemini", model="m"),
            LlmUnavailableError,
            "llm_auth_failed",
        ),
        (
            E.NotFoundError(message="no such model", model="m", llm_provider="gemini"),
            LlmUnavailableError,
            "llm_model_not_found",
        ),
        (
            E.RateLimitError(message="quota", llm_provider="gemini", model="m"),
            LlmTransientError,
            "llm_rate_limited",
        ),
        (E.Timeout(message="slow", model="m", llm_provider="gemini"), LlmTransientError, "llm_timeout"),
        (
            E.APIConnectionError(message="down", llm_provider="gemini", model="m", request=None),
            LlmTransientError,
            "llm_unavailable",
        ),
    ],
)
def test_failures_get_distinct_codes(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected_type: type, code: str
) -> None:
    script(monkeypatch, [error])
    with pytest.raises(expected_type) as caught:
        provider().generate_json("sys", "ping", SCHEMA, max_output_tokens=64)
    assert caught.value.code == code  # type: ignore[attr-defined]


def test_test_endpoint_reports_the_specific_code(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    register(client)
    body = {"mode": "commercial", "model": "gemini/gemini-3.8-flash", "api_key": "k"}

    script(monkeypatch, [E.RateLimitError(message="quota", llm_provider="gemini", model="m")])
    res = client.post(f"{API}/llm/test", json=body)
    assert res.status_code == 409 and res.json()["error"]["code"] == "llm_rate_limited"

    script(monkeypatch, [unsupported("top_p")])
    res = client.post(f"{API}/llm/test", json=body)
    assert res.status_code == 409 and res.json()["error"]["code"] == "llm_request_rejected"
    assert "top_p" in res.json()["error"]["message"]

    # temperature만 거부하는 모델은 인자를 빼고 성공한다
    script(monkeypatch, [unsupported("temperature"), ok_response()])
    res = client.post(f"{API}/llm/test", json=body)
    assert res.status_code == 200 and res.json()["ok"] is True
