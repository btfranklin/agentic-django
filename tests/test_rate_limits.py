from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest
from django.test import override_settings
from django.utils import timezone

from agentic_django.models import AgentRequestLimit
from agentic_django.rate_limits import admit_request


@pytest.mark.django_db()
def test_request_limit_expires_without_cache_support(user: Any) -> None:
    with override_settings(CACHES={
        "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
    }):
        assert admit_request(user, 1, 60)
        assert not admit_request(user, 1, 60)
        AgentRequestLimit.objects.update(
            window_started_at=timezone.now() - timedelta(seconds=61),
        )
        assert admit_request(user, 1, 60)
        assert not admit_request(user, 1, 60)
    assert AgentRequestLimit.objects.get(owner=user).count == 1


@pytest.mark.django_db()
def test_request_limits_are_per_owner_and_cascade(user: Any) -> None:
    other_user = type(user).objects.create_user(username="other")
    assert admit_request(user, 1, 60)
    assert admit_request(other_user, 1, 60)
    assert not admit_request(user, 1, 60)
    other_user.delete()
    assert AgentRequestLimit.objects.count() == 1


@pytest.mark.parametrize("max_calls", [1, 3])
def test_concurrent_requests_cannot_exceed_limit(
    tmp_path: Path, max_calls: int,
) -> None:
    # A file database gives each thread a separate connection with normal lock waits.
    result = subprocess.run(
        [
            sys.executable, "-m", "tests.scenarios.concurrent_rate_limits",
            str(tmp_path / "rate.sqlite3"), str(max_calls),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
