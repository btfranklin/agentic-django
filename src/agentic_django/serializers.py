from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Mapping
from typing import Protocol, runtime_checkable

from agents import Agent
from agents.items import RunItem, TResponseInputItem
from agents.stream_events import (
    AgentUpdatedStreamEvent,
    RawResponsesStreamEvent,
    RunItemStreamEvent,
    StreamEvent,
)
from pydantic import BaseModel

from agentic_django.types import JsonObject, JsonValue, input_items, json_value


@runtime_checkable
class Serializer(Protocol):
    def serialize(self, value: object) -> JsonValue: ...
    def deserialize(self, value: JsonValue) -> JsonValue: ...


@runtime_checkable
class ItemSerializer(Protocol):
    def serialize(self, value: TResponseInputItem) -> JsonValue: ...
    def deserialize(self, value: JsonValue) -> TResponseInputItem: ...


@runtime_checkable
class EventSerializer(Protocol):
    def serialize(self, value: StreamEvent) -> JsonObject | None: ...


class JsonSerializer:
    def serialize(self, value: object) -> JsonValue:
        return _to_jsonable(value)

    def deserialize(self, value: JsonValue) -> JsonValue:
        return json_value(value)


class SessionItemSerializer:
    def serialize(self, value: TResponseInputItem) -> JsonValue:
        return _to_jsonable(value)

    def deserialize(self, value: JsonValue) -> TResponseInputItem:
        return input_items([value])[0]


class StreamEventSerializer:
    def serialize(self, value: StreamEvent) -> JsonObject | None:
        if isinstance(value, RawResponsesStreamEvent):
            return None
        if isinstance(value, RunItemStreamEvent):
            return {
                "type": value.type,
                "name": value.name,
                "item": _serialize_run_item(value.item),
            }
        if isinstance(value, AgentUpdatedStreamEvent):
            return {"type": value.type, "agent": _serialize_agent(value.new_agent)}

    def deserialize(self, value: JsonValue) -> JsonValue:
        return json_value(value)


def _to_jsonable(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        return json_value(value.model_dump(mode="json"))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _to_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, Iterator)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return json_value(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_jsonable(model_dump())
    return str(value)


def _serialize_agent(agent: Agent[object]) -> JsonObject:
    return {"name": agent.name, "class": agent.__class__.__name__}


def _serialize_run_item(item: RunItem) -> JsonObject:
    payload: JsonObject = {"type": item.type, "raw_item": _to_jsonable(item.raw_item)}
    for name in ("agent", "source_agent", "target_agent"):
        agent: object = getattr(item, name, None)
        if isinstance(agent, Agent):
            payload[name] = _serialize_agent(agent)
    return payload
