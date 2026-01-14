from __future__ import annotations

import pytest
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
