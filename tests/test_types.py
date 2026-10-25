from __future__ import annotations

import json

import pytest
from agents import RunConfig
from agents.lifecycle import RunHooks
from agents.run_error_handlers import RunErrorHandlerInput, RunErrorHandlers
from django.contrib.auth.models import User
from django.test import Client

from agentic_django.models import AgentRun, AgentSession
from agentic_django.services import submit_agent_run
from agentic_django.types import JsonObject, input_items, json_value, run_options


def test_json_run_config_uses_strict_sdk_field_types() -> None:
    options = run_options(
        {
            "run_config": {
                "tracing_disabled": True,
                "model_settings": {"temperature": 0.2},
            },
        }
    )
    config = options["run_config"]
    assert isinstance(config, RunConfig)
    assert config.tracing_disabled is True
    assert config.model_settings is not None
    assert config.model_settings.temperature == 0.2


@pytest.mark.parametrize(
    "config",
    [
        {"tracing_disabled": "false"},
        {"unknown": True},
        {"model_settings": {"temperature": "hot"}},
        {"model_settings": {"unknown": 1}},
    ],
)
def test_json_run_config_rejects_invalid_fields(config: object) -> None:
    with pytest.raises(ValueError, match="Invalid run_config"):
        run_options({"run_config": config})


def test_settings_callbacks_remain_typed_sdk_objects() -> None:
    hooks = RunHooks[object]()

    def handle_error(value: RunErrorHandlerInput[object]) -> str:
        return "stopped"

    handlers: RunErrorHandlers[object] = {"max_turns": handle_error}
    options = run_options({"hooks": hooks, "error_handlers": handlers})
    assert options["hooks"] is hooks
    assert options["error_handlers"] is handlers


@pytest.mark.parametrize(
    "value",
    [
        {"max_turns": True},
        {"auto_previous_response_id": 1},
        {"hooks": "invalid"},
        {"error_handlers": {"unknown": lambda: None}},
        {"error_handlers": {"max_turns": "invalid"}},
        {"session": "cannot replace the stored session"},
        {"context": "use the context factory"},
    ],
)
def test_run_options_reject_invalid_types_and_reserved_keys(value: object) -> None:
    with pytest.raises(ValueError):
        run_options(value)


def test_json_validation_rejects_non_string_keys_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="keys"):
        json_value({1: "invalid"})
    with pytest.raises(ValueError, match="finite"):
        json_value({"nested": [float("inf")]})


def test_sdk_input_validation_preserves_function_calls() -> None:
    items = input_items(
        [
            {
                "type": "function_call",
                "name": "lookup",
                "arguments": "{}",
                "call_id": "1",
            },
            {"type": "function_call_output", "call_id": "1", "output": "found"},
        ]
    )
    assert len(items) == 2
    assert items[0].get("type") == "function_call"
    assert items[1].get("type") == "function_call_output"


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "config",
    [
        {"run_config": {"tracing_disabled": "false"}},
        {"run_config": {"unknown": 2}},
        7,
    ],
)
def test_request_rejects_invalid_nested_config_without_records(
    client: Client,
    user: User,
    config: object,
) -> None:
    client.force_login(user)
    response = client.post(
        "/runs/",
        data=json.dumps(
            {
                "session_key": "typed",
                "input": "hello",
                "config": config,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not AgentSession.objects.exists()
    assert not AgentRun.objects.exists()


@pytest.mark.django_db()
def test_request_accepts_json_run_config(
    client: Client,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.services.enqueue_agent_run", lambda run_id: None
    )
    response = client.post(
        "/runs/",
        data=json.dumps(
            {
                "session_key": "typed",
                "input": [{"role": "user", "content": "hello"}],
                "config": {"run_config": {"tracing_disabled": True}},
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    run = AgentRun.objects.get()
    assert run.metadata == {"run_options": {"run_config": {"tracing_disabled": True}}}


@pytest.mark.django_db()
def test_submission_rejects_invalid_metadata_before_creating_records(
    user: User,
) -> None:
    metadata: JsonObject = {"run_options": {"max_turns": "invalid"}}
    with pytest.raises(ValueError, match="max_turns"):
        submit_agent_run(
            owner=user,
            session_key="typed",
            agent_key="default",
            input_payload="hello",
            metadata=metadata,
        )
    assert not AgentSession.objects.exists()
    assert not AgentRun.objects.exists()


def test_sdk_input_validation_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="SDK input schema"):
        input_items([{"role": "user", "content": "hello", "unknown": 1}])
