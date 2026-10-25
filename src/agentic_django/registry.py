from __future__ import annotations

from collections.abc import Callable

from agents import Agent
from django.utils.module_loading import import_string

from agentic_django.conf import get_settings


def _checked_factory(factory: object) -> Callable[[], Agent[object]]:
    if not callable(factory):
        raise ValueError("Agent registry must map strings to agent factories")

    def build() -> Agent[object]:
        agent: object = factory()
        if not isinstance(agent, Agent):
            raise ValueError("Agent factory must return an Agent")
        # Context types are chosen by the host. The context factory must return
        # the type required by each registered agent.
        return agent

    return build


def get_agent_registry() -> dict[str, Callable[[], Agent[object]]]:
    registry_path = get_settings().agent_registry
    registry_factory: object = import_string(registry_path)
    if not callable(registry_factory):
        raise ValueError("Agent registry must be callable")
    registry: object = registry_factory()
    if not isinstance(registry, dict):
        raise ValueError("Agent registry must return a dict of agent factories")
    checked: dict[str, Callable[[], Agent[object]]] = {}
    for key, factory in registry.items():
        if not isinstance(key, str):
            raise ValueError("Agent registry must map strings to agent factories")
        checked[key] = _checked_factory(factory)
    return checked


def get_agent(agent_key: str) -> Agent[object]:
    registry = get_agent_registry()
    if agent_key not in registry:
        raise KeyError(f"Unknown agent key: {agent_key}")
    return registry[agent_key]()
