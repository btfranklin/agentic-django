from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from agents import Agent
from agents.items import ToolCallItem
from agents.stream_events import AgentUpdatedStreamEvent, RunItemStreamEvent
from pydantic import BaseModel

from agentic_django.serializers import (
    JsonSerializer,
    StreamEventSerializer,
    _to_jsonable,
)


class ExampleModel(BaseModel):
    name: str
    value: int | None = None


@dataclass
class ExampleData:
    name: str
    count: int


def test_to_jsonable_handles_dataclass() -> None:
    payload = _to_jsonable(ExampleData(name="hi", count=2))
    assert payload == {"name": "hi", "count": 2}


def test_to_jsonable_handles_pydantic() -> None:
    payload = _to_jsonable(ExampleModel(name="hi"))
    assert payload == {"name": "hi", "value": None}


def test_to_jsonable_normalizes_model_dump_fallback() -> None:
    class CustomModel:
        def model_dump(self) -> dict[str, Any]:
            return {"day": date(2026, 9, 5), "nested": ExampleModel(name="hi")}

    assert _to_jsonable(CustomModel()) == {
        "day": "2026-09-05",
        "nested": {"name": "hi", "value": None},
    }


def test_serializer_round_trip() -> None:
    serializer = JsonSerializer()
    payload = {"items": [1, 2, 3]}
    assert serializer.deserialize(serializer.serialize(payload)) == payload

def test_stream_event_serializer_handles_events() -> None:
    serializer = StreamEventSerializer()
    agent = Agent(name="Test Agent", instructions="hi")
    run_item = ToolCallItem(agent=agent, raw_item={"tool": "example"})
    run_item_event = RunItemStreamEvent(name="tool_called", item=run_item)
    agent_event = AgentUpdatedStreamEvent(new_agent=agent)

    run_item_payload = serializer.serialize(run_item_event)
    agent_payload = serializer.serialize(agent_event)

    assert run_item_payload["name"] == "tool_called"
    assert agent_payload["agent"]["name"] == "Test Agent"
