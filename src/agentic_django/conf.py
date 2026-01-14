from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

VALID_RUN_STATUSES = {"pending", "running", "completed", "failed"}


@dataclass(frozen=True)
class AgenticDjangoSettings:
    agent_registry: str
    default_agent_key: str
    session_backend: str
    session_item_serializer: str
    default_run_options: dict[str, Any]
    serializer: str
    enable_events: bool
    event_serializer: str
    cleanup_policy: dict[str, Any]
    concurrency_limit: int | None
    context_factory: str | None
    rate_limit: str | None
    max_input_bytes: int | None
    max_input_items: int | None
    startup_recovery: str


def _get_setting(name: str, default: Any) -> Any:
    if hasattr(settings, name):
        return getattr(settings, name)
    return default


def get_settings() -> AgenticDjangoSettings:
    return AgenticDjangoSettings(
        agent_registry=_get_setting(
            "AGENTIC_DJANGO_AGENT_REGISTRY",
            "",
        ),
        default_agent_key=_get_setting(
            "AGENTIC_DJANGO_DEFAULT_AGENT_KEY",
            "default",
        ),
        session_backend=_get_setting(
            "AGENTIC_DJANGO_SESSION_BACKEND",
            "agentic_django.sessions.DatabaseSession",
        ),
        session_item_serializer=_get_setting(
            "AGENTIC_DJANGO_SESSION_ITEM_SERIALIZER",
            "agentic_django.serializers.SessionItemSerializer",
        ),
        default_run_options=_get_setting(
            "AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS",
            {},
        ),
        serializer=_get_setting(
            "AGENTIC_DJANGO_SERIALIZER",
            "agentic_django.serializers.JsonSerializer",
        ),
        enable_events=_get_setting(
            "AGENTIC_DJANGO_ENABLE_EVENTS",
            False,
        ),
        event_serializer=_get_setting(
            "AGENTIC_DJANGO_EVENT_SERIALIZER",
            "agentic_django.serializers.StreamEventSerializer",
        ),
        cleanup_policy=_get_setting(
            "AGENTIC_DJANGO_CLEANUP_POLICY",
            {},
        ),
        concurrency_limit=_get_setting(
            "AGENTIC_DJANGO_CONCURRENCY_LIMIT",
            None,
        ),
        context_factory=_get_setting(
            "AGENTIC_DJANGO_CONTEXT_FACTORY",
            None,
        ),
        rate_limit=_get_setting("AGENTIC_DJANGO_RATE_LIMIT", None),
        max_input_bytes=_get_setting("AGENTIC_DJANGO_MAX_INPUT_BYTES", None),
        max_input_items=_get_setting("AGENTIC_DJANGO_MAX_INPUT_ITEMS", None),
        startup_recovery=_get_setting("AGENTIC_DJANGO_STARTUP_RECOVERY", "requeue"),
    )


def get_concurrency_limit() -> int:
    configured = get_settings().concurrency_limit
    if configured is None:
        cpu_count = os.cpu_count() or 1
        return max(1, cpu_count)
    if configured < 1:
        raise ImproperlyConfigured("AGENTIC_DJANGO_CONCURRENCY_LIMIT must be >= 1")
    return configured


def import_from_path(path: str) -> Any:
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


def normalize_cleanup_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    if not policy:
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
    unknown = set(policy.keys()) - allowed_keys
    if unknown:
        unknown_keys = ", ".join(sorted(unknown))
        raise ImproperlyConfigured(
            f"AGENTIC_DJANGO_CLEANUP_POLICY has unknown keys: {unknown_keys}"
        )

    normalized: dict[str, Any] = {}
    for key in ("events_days", "runs_days", "sessions_days", "batch_size"):
        if key not in policy:
            continue
        value = policy[key]
        if value is None:
            continue
        if not isinstance(value, int) or value < 1:
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
            normalized_statuses = [str(status) for status in statuses]
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

    import_from_path(config.agent_registry)
    import_from_path(config.session_backend)
    import_from_path(config.session_item_serializer)
    import_from_path(config.serializer)

    if config.event_serializer:
        import_from_path(config.event_serializer)

    if config.context_factory:
        import_from_path(config.context_factory)

    parse_rate_limit(config.rate_limit)
    if config.max_input_bytes is not None and config.max_input_bytes < 1:
        raise ImproperlyConfigured("AGENTIC_DJANGO_MAX_INPUT_BYTES must be >= 1")
    if config.max_input_items is not None and config.max_input_items < 1:
        raise ImproperlyConfigured("AGENTIC_DJANGO_MAX_INPUT_ITEMS must be >= 1")
    if config.startup_recovery not in {"ignore", "fail", "requeue"}:
        raise ImproperlyConfigured(
            "AGENTIC_DJANGO_STARTUP_RECOVERY must be 'ignore', 'fail', or 'requeue'"
        )
    normalize_cleanup_policy(config.cleanup_policy)
