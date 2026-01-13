from __future__ import annotations

import dataclasses
import json
from typing import Any

from agents.stream_events import (
    AgentUpdatedStreamEvent,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    StreamEvent,
)
from pydantic import BaseModel
from django.utils.html import escape
from django.utils.safestring import mark_safe


class JsonSerializer:
    def serialize(self, value: Any) -> Any:
        return _to_jsonable(value)

    def deserialize(self, value: Any) -> Any:
        return value


class SessionItemSerializer:
    def serialize(self, value: Any) -> Any:
        return _to_jsonable(value)

    def deserialize(self, value: Any) -> Any:
        return value


class StreamEventSerializer:
    def serialize(self, value: StreamEvent) -> dict[str, Any] | None:
        if isinstance(value, RawResponsesStreamEvent):
            return None
        if isinstance(value, RunItemStreamEvent):
            return {
                "type": value.type,
                "name": value.name,
                "item": _serialize_run_item(value.item),
            }
        if isinstance(value, AgentUpdatedStreamEvent):
            return {
                "type": value.type,
                "agent": _serialize_agent(value.new_agent),
            }
        return {
            "type": "unknown",
            "data": _to_jsonable(value),
        }

    def deserialize(self, value: Any) -> Any:
        return value


def pretty_json(value: Any) -> str:
    text = json.dumps(_to_jsonable(value), indent=2, sort_keys=True, ensure_ascii=True)
    return mark_safe(escape(text))


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(exclude_none=True)
    if dataclasses.is_dataclass(value):
        return {field.name: _to_jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


def _serialize_agent(agent: Any) -> dict[str, Any]:
    return {
        "name": getattr(agent, "name", None),
        "class": agent.__class__.__name__,
    }


def _serialize_run_item(item: Any) -> dict[str, Any]:
    payload = {
        "type": getattr(item, "type", None),
        "raw_item": _to_jsonable(getattr(item, "raw_item", None)),
    }
    agent = getattr(item, "agent", None)
    if agent is not None:
        payload["agent"] = _serialize_agent(agent)
    source_agent = getattr(item, "source_agent", None)
    if source_agent is not None:
        payload["source_agent"] = _serialize_agent(source_agent)
    target_agent = getattr(item, "target_agent", None)
    if target_agent is not None:
        payload["target_agent"] = _serialize_agent(target_agent)
    return payload
