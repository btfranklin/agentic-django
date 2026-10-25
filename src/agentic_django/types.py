"""Types and validation for JSON and SDK inputs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from functools import cache
from typing import TypedDict, cast

from agents import RunConfig
from agents.items import TResponseInputItem
from agents.lifecycle import RunHooks, RunHooksBase
from agents.run_error_handlers import RunErrorHandlers
from pydantic import ConfigDict, TypeAdapter, ValidationError
from pydantic.dataclasses import dataclass, is_pydantic_dataclass, rebuild_dataclass

# Recursive JSON values cannot contain arbitrary Python objects.
type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
type JsonObject = dict[str, JsonValue]


class CleanupPolicy(TypedDict, total=False):
    events_days: int
    runs_days: int
    sessions_days: int
    runs_statuses: list[str]
    sessions_require_empty: bool
    batch_size: int


class RunOptions(TypedDict, total=False):
    hooks: RunHooks[object] | None
    error_handlers: RunErrorHandlers[object] | None
    max_turns: int | None
    run_config: RunConfig | None
    previous_response_id: str | None
    auto_previous_response_id: bool
    conversation_id: str | None


def json_value(
    value: object,
    *,
    max_depth: int | None = None,
    depth: int = 0,
) -> JsonValue:
    """Check JSON data without coercing values or silently removing fields."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if max_depth is not None and depth >= max_depth:
        raise ValueError("JSON payload is nested too deeply")
    if isinstance(value, Mapping):
        result: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            result[key] = json_value(item, max_depth=max_depth, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [
            json_value(item, max_depth=max_depth, depth=depth + 1) for item in value
        ]
    raise ValueError("Value must be JSON data")


@cache
def _input_adapter() -> TypeAdapter[list[TResponseInputItem]]:
    return TypeAdapter(list[TResponseInputItem])


def input_items(value: object) -> list[TResponseInputItem]:
    adapter = _input_adapter()
    try:
        items = adapter.validate_python(value, strict=True, extra="forbid")
        # SDK Iterable fields validate lazily. JSON mode reads and validates
        # their members before these items reach storage or an HTTP response.
        payload: object = adapter.dump_python(items, mode="json", warnings="error")
        normalized = json_value(payload)
    except ValueError as exc:
        raise ValueError("Input items must match the SDK input schema") from exc
    # The adapter checked the SDK schema; JSON mode replaces iterables with
    # reusable lists without changing the item fields.
    return cast(list[TResponseInputItem], normalized)


def run_input(value: object) -> str | list[TResponseInputItem]:
    if isinstance(value, str):
        return value
    return input_items(value)


def run_options(value: object) -> RunOptions:
    """Check the options that can be stored in run metadata."""
    if not isinstance(value, dict):
        raise ValueError("Run options must be an object")
    allowed = RunOptions.__optional_keys__
    if set(value) - allowed:
        raise ValueError("Unknown run option")
    result: RunOptions = {}
    if "max_turns" in value:
        turns = value["max_turns"]
        if turns is not None and (type(turns) is not int or turns < 1):
            raise ValueError("max_turns must be an integer >= 1 or null")
        result["max_turns"] = turns
    for key in ("previous_response_id", "conversation_id"):
        item = value.get(key)
        if key in value:
            if item is not None and not isinstance(item, str):
                raise ValueError(f"{key} must be a string or null")
            if key == "previous_response_id":
                result["previous_response_id"] = item
            else:
                result["conversation_id"] = item
    if "auto_previous_response_id" in value:
        auto = value["auto_previous_response_id"]
        if not isinstance(auto, bool):
            raise ValueError("auto_previous_response_id must be a boolean")
        result["auto_previous_response_id"] = auto
    if "run_config" in value:
        config = value["run_config"]
        if isinstance(config, dict):
            # RunConfig is an SDK dataclass. Its fields can contain SDK objects.
            # Pydantic checks the dataclass fields before construction.
            try:
                config = _config_adapter().validate_json(
                    json.dumps(json_value(config)), strict=True, extra="forbid"
                )
            except ValidationError as exc:
                raise ValueError("Invalid run_config") from exc
        if config is not None and not isinstance(config, RunConfig):
            raise ValueError("run_config must be an object or null")
        result["run_config"] = config
    if "hooks" in value:
        hooks = value["hooks"]
        if hooks is not None and not isinstance(hooks, RunHooksBase):
            raise ValueError("hooks must be RunHooks or null")
        result["hooks"] = hooks
    if "error_handlers" in value:
        handlers = value["error_handlers"]
        if handlers is None:
            result["error_handlers"] = None
        else:
            if (
                not isinstance(handlers, dict)
                or set(handlers) - RunErrorHandlers.__optional_keys__
            ):
                raise ValueError("Invalid error_handlers")
            if not all(callable(handler) for handler in handlers.values()):
                raise ValueError("Error handlers must be callable")
            # The SDK handler callback accepts its typed input. Callable checks
            # cannot inspect a host function's annotations or result type.
            result["error_handlers"] = cast(RunErrorHandlers[object], handlers)
    return result


@dataclass(config=ConfigDict(arbitrary_types_allowed=True, extra="forbid"))
# The SDK declares some inherited fields with Any. The generated constructor
# retains these SDK types; this exception does not apply to package data.
class _ValidatedRunConfig(RunConfig):  # type: ignore[explicit-any]
    """Apply SDK field types to JSON configuration before SDK execution."""


@cache
def _config_adapter() -> TypeAdapter[RunConfig]:
    import agents
    from agents import run_config as sdk_config
    from agents.sandbox.manifest import Manifest
    from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
    from agents.sandbox.session.sandbox_client import BaseSandboxClient
    from agents.sandbox.session.sandbox_session_state import SandboxSessionState
    from agents.sandbox.snapshot import SnapshotBase, SnapshotSpec

    # The SDK imports these annotation names only under TYPE_CHECKING. Supply
    # them to Pydantic without changing the SDK module's global namespace.
    namespace: dict[str, object] = {
        **vars(agents),
        **vars(sdk_config),
        "Manifest": Manifest,
        "BaseSandboxSession": BaseSandboxSession,
        "BaseSandboxClient": BaseSandboxClient,
        "SandboxSessionState": SandboxSessionState,
        "SnapshotBase": SnapshotBase,
        "SnapshotSpec": SnapshotSpec,
    }
    assert is_pydantic_dataclass(_ValidatedRunConfig)
    rebuild_dataclass(_ValidatedRunConfig, _types_namespace=namespace)
    return TypeAdapter(_ValidatedRunConfig)
