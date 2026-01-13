from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from agentic_django.conf import get_concurrency_limit, get_settings, validate_settings


def test_get_settings_defaults() -> None:
    settings = get_settings()
    assert settings.default_agent_key == "default"
    assert settings.session_backend.endswith("DatabaseSession")
    assert settings.session_item_serializer.endswith("SessionItemSerializer")
    assert settings.serializer.endswith("JsonSerializer")


def test_get_concurrency_limit_from_cpu() -> None:
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=None):
        assert get_concurrency_limit() >= 1


def test_get_concurrency_limit_invalid() -> None:
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=0):
        with pytest.raises(ImproperlyConfigured):
            get_concurrency_limit()


def test_validate_settings_requires_registry() -> None:
    with override_settings(AGENTIC_DJANGO_AGENT_REGISTRY=""):
        with pytest.raises(ImproperlyConfigured):
            validate_settings()


def test_validate_settings_imports_paths() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.support.get_agent_registry",
        AGENTIC_DJANGO_SESSION_BACKEND="agentic_django.sessions.DatabaseSession",
        AGENTIC_DJANGO_SESSION_ITEM_SERIALIZER="agentic_django.serializers.SessionItemSerializer",
        AGENTIC_DJANGO_SERIALIZER="agentic_django.serializers.JsonSerializer",
    ):
        validate_settings()


def test_validate_settings_rate_limit_invalid() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.support.get_agent_registry",
        AGENTIC_DJANGO_RATE_LIMIT="bad",
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_settings()


def test_validate_settings_startup_recovery_invalid() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.support.get_agent_registry",
        AGENTIC_DJANGO_STARTUP_RECOVERY="maybe",
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_settings()


def test_validate_settings_cleanup_policy_invalid_type() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.support.get_agent_registry",
        AGENTIC_DJANGO_CLEANUP_POLICY="bad",
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_settings()


def test_validate_settings_cleanup_policy_invalid_status() -> None:
    with override_settings(
        AGENTIC_DJANGO_AGENT_REGISTRY="tests.support.get_agent_registry",
        AGENTIC_DJANGO_CLEANUP_POLICY={"runs_statuses": ["unknown"]},
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_settings()
