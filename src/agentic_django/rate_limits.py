from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

from django.db.models import F
from django.utils import timezone

from agentic_django.models import AgentRequestLimit


def admit_request(owner: AbstractBaseUser, max_calls: int, period_seconds: int) -> bool:
    """Reserve one request in the owner's current rate-limit window."""
    now = timezone.now()
    counter, _ = AgentRequestLimit.objects.get_or_create(
        owner_id=owner.pk,
        defaults={"window_started_at": now},
    )
    counters = AgentRequestLimit.objects.filter(pk=counter.pk)
    counters.filter(
        window_started_at__lte=now - timedelta(seconds=period_seconds),
    ).update(window_started_at=now, count=0)
    return bool(counters.filter(count__lt=max_calls).update(count=F("count") + 1))
