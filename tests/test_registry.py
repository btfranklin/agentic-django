from __future__ import annotations

from collections.abc import Callable

import pytest
from agents import Agent
from django.test import override_settings

from agentic_django.registry import get_agent, get_agent_registry


def test_get_agent_registry_returns_dict() -> None:
    registry = get_agent_registry()
    assert isinstance(registry, dict)
    assert "default" in registry


def test_get_agent_registry_requires_dict() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.test_registry.bad_registry"
    ):
        with pytest.raises(ValueError):
            get_agent_registry()


def test_get_agent_returns_factory_result() -> None:
    agent = get_agent("default")
    assert agent is not None


def test_get_agent_unknown_key() -> None:
    with pytest.raises(KeyError):
        get_agent("missing")


def bad_registry() -> list[str]:
    return ["not", "a", "dict"]


@pytest.mark.parametrize("registry_name", ["bad_key_registry", "bad_factory_registry"])
def test_get_agent_registry_rejects_invalid_entries(registry_name: str) -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY=f"tests.test_registry.{registry_name}"
    ):
        with pytest.raises(ValueError, match="map strings to agent factories"):
            get_agent_registry()


def bad_key_registry() -> dict[object, Callable[[], Agent[object]]]:
    return {1: lambda: Agent[object](name="test")}


def bad_factory_registry() -> dict[str, object]:
    return {"default": "not callable"}


def bad_agent_registry() -> dict[str, Callable[[], object]]:
    return {"default": lambda: object()}


def test_get_agent_rejects_non_agent_factory_result() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.test_registry.bad_agent_registry"
    ):
        with pytest.raises(ValueError, match="must return an Agent"):
            get_agent("default")
