from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agents import Agent
from django.utils.module_loading import import_string

from agentic_django.conf import get_settings


def get_agent_registry() -> dict[str, Callable[[], Agent[Any]]]:
    registry_path = get_settings().agent_registry
    registry_factory = import_string(registry_path)
    registry = registry_factory()
    if not isinstance(registry, dict):
        raise ValueError("Agent registry must return a dict of agent factories")
    return registry


def get_agent(agent_key: str) -> Agent[Any]:
    registry = get_agent_registry()
    if agent_key not in registry:
        raise KeyError(f"Unknown agent key: {agent_key}")
    return registry[agent_key]()
