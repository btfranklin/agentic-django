from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from agentic_django.serializers import EventSerializer, ItemSerializer, Serializer
from agentic_django.types import CleanupPolicy, RunOptions, run_options

VALID_RUN_STATUSES = {"pending", "running", "completed", "failed"}


@dataclass(frozen=True)
class AgenticDjangoSettings:
    agent_registry: str
    default_agent_key: str
    session_backend: str
    session_item_serializer: str
    default_run_options: RunOptions
    serializer: str
    enable_events: bool
    event_serializer: str
    cleanup_policy: CleanupPolicy
    concurrency_limit: int | None
    context_factory: str | None
    rate_limit: str | None
    max_input_bytes: int | None
    max_input_items: int | None


def _get_setting(name: str, default: object = None) -> object:
    return getattr(settings, name, default)


def _string(name: str, default: str) -> str:
    value = _get_setting(name, default)
    if not isinstance(value, str):
        raise ImproperlyConfigured(f"{name} must be a string")
    return value


def _optional_string(name: str) -> str | None:
    value = _get_setting(name)
    if value is not None and not isinstance(value, str):
        raise ImproperlyConfigured(f"{name} must be a string or None")
    return value


def _positive_integer(name: str) -> int | None:
    value = _get_setting(name)
    if value is not None and (type(value) is not int or value < 1):
        raise ImproperlyConfigured(f"{name} must be an integer >= 1 or None")
    return value


def get_settings() -> AgenticDjangoSettings:
    enabled = _get_setting("AGENTIC_DJANGO_ENABLE_EVENTS", False)
    if not isinstance(enabled, bool):
        raise ImproperlyConfigured("AGENTIC_DJANGO_ENABLE_EVENTS must be a boolean")
    try:
        options = run_options(_get_setting("AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS", {}))
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS: {exc}"
        ) from exc
    return AgenticDjangoSettings(
        agent_registry=_string("AGENTIC_DJANGO_AGENT_REGISTRY", ""),
        default_agent_key=_string("AGENTIC_DJANGO_DEFAULT_AGENT_KEY", "default"),
        session_backend=_string(
            "AGENTIC_DJANGO_SESSION_BACKEND",
            "agentic_django.sessions.DatabaseSession",
        ),
        session_item_serializer=_string(
            "AGENTIC_DJANGO_SESSION_ITEM_SERIALIZER",
            "agentic_django.serializers.SessionItemSerializer",
        ),
        default_run_options=options,
        serializer=_string(
            "AGENTIC_DJANGO_SERIALIZER", "agentic_django.serializers.JsonSerializer"
        ),
        enable_events=enabled,
        event_serializer=_string(
            "AGENTIC_DJANGO_EVENT_SERIALIZER",
            "agentic_django.serializers.StreamEventSerializer",
        ),
        cleanup_policy=normalize_cleanup_policy(
            _get_setting("AGENTIC_DJANGO_CLEANUP_POLICY")
        ),
        concurrency_limit=_positive_integer("AGENTIC_DJANGO_CONCURRENCY_LIMIT"),
        context_factory=_optional_string("AGENTIC_DJANGO_CONTEXT_FACTORY"),
        rate_limit=_optional_string("AGENTIC_DJANGO_RATE_LIMIT"),
        max_input_bytes=_positive_integer("AGENTIC_DJANGO_MAX_INPUT_BYTES"),
        max_input_items=_positive_integer("AGENTIC_DJANGO_MAX_INPUT_ITEMS"),
    )


def get_concurrency_limit() -> int:
    configured = get_settings().concurrency_limit
    if configured is None:
        cpu_count = os.cpu_count() or 1
        return max(1, cpu_count)
    return configured


def import_from_path(path: str) -> object:
    return import_string(path)


def parse_rate_limit(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        count_str, period_str = value.split("/", 1)
        count = int(count_str)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "AGENTIC_DJANGO_RATE_LIMIT must be like '20/m'"
        ) from exc
    period_map = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    period_seconds = period_map.get(period_str)
    if count < 1 or period_seconds is None:
        raise ImproperlyConfigured("AGENTIC_DJANGO_RATE_LIMIT must be like '20/m'")
    return count, period_seconds


def normalize_cleanup_policy(policy: object) -> CleanupPolicy:
    if policy is None or policy == {}:
        return {}
    if not isinstance(policy, dict):
        raise ImproperlyConfigured("AGENTIC_DJANGO_CLEANUP_POLICY must be a dict.")

    allowed_keys = {
        "events_days",
        "runs_days",
        "sessions_days",
        "runs_statuses",
        "sessions_require_empty",
        "batch_size",
    }
    if not all(isinstance(key, str) for key in policy):
        raise ImproperlyConfigured("Cleanup policy keys must be strings")
    unknown = set(policy.keys()) - allowed_keys
    if unknown:
        unknown_keys = ", ".join(sorted(unknown))
        raise ImproperlyConfigured(
            f"AGENTIC_DJANGO_CLEANUP_POLICY has unknown keys: {unknown_keys}"
        )

    normalized: CleanupPolicy = {}
    numeric_keys: tuple[
        Literal["events_days", "runs_days", "sessions_days", "batch_size"], ...
    ] = (
        "events_days",
        "runs_days",
        "sessions_days",
        "batch_size",
    )
    for key in numeric_keys:
        if key not in policy:
            continue
        value = policy[key]
        if value is None:
            continue
        if type(value) is not int or value < 1:
            raise ImproperlyConfigured(
                f"AGENTIC_DJANGO_CLEANUP_POLICY.{key} must be >= 1"
            )
        normalized[key] = value

    if "runs_statuses" in policy:
        statuses = policy["runs_statuses"]
        if statuses is None:
            pass
        elif not isinstance(statuses, (list, tuple, set)):
            raise ImproperlyConfigured(
                "AGENTIC_DJANGO_CLEANUP_POLICY.runs_statuses must be a list"
            )
        else:
            if not all(isinstance(status, str) for status in statuses):
                raise ImproperlyConfigured("Cleanup run statuses must be strings")
            normalized_statuses = list(statuses)
            invalid = sorted(set(normalized_statuses) - VALID_RUN_STATUSES)
            if invalid:
                raise ImproperlyConfigured(
                    "AGENTIC_DJANGO_CLEANUP_POLICY.runs_statuses has invalid values: "
                    + ", ".join(invalid)
                )
            if not normalized_statuses:
                raise ImproperlyConfigured(
                    "AGENTIC_DJANGO_CLEANUP_POLICY.runs_statuses cannot be empty"
                )
            normalized["runs_statuses"] = normalized_statuses

    if "sessions_require_empty" in policy:
        require_empty = policy["sessions_require_empty"]
        if require_empty is None:
            pass
        elif not isinstance(require_empty, bool):
            raise ImproperlyConfigured(
                "AGENTIC_DJANGO_CLEANUP_POLICY.sessions_require_empty must be a boolean"
            )
        else:
            normalized["sessions_require_empty"] = require_empty

    return normalized


def validate_settings() -> None:
    config = get_settings()
    if not config.agent_registry:
        raise ImproperlyConfigured("AGENTIC_DJANGO_AGENT_REGISTRY is required.")

    if not callable(import_from_path(config.agent_registry)):
        raise ImproperlyConfigured("Agent registry must be a callable")
    backend = import_from_path(config.session_backend)
    if not callable(getattr(backend, "get_or_create", None)):
        raise ImproperlyConfigured("Session backend must define get_or_create")
    for path, protocol in (
        (config.serializer, Serializer),
        (config.session_item_serializer, ItemSerializer),
        (config.event_serializer, EventSerializer),
    ):
        if not path:
            continue
        factory = import_from_path(path)
        if not callable(factory):
            raise ImproperlyConfigured(f"{path} must be a serializer factory")
        component: object = factory()
        if not isinstance(component, protocol):
            raise ImproperlyConfigured(
                f"{path} does not implement its serializer protocol"
            )
    if config.context_factory and not callable(
        import_from_path(config.context_factory)
    ):
        raise ImproperlyConfigured("Context factory must be callable")
    parse_rate_limit(config.rate_limit)
