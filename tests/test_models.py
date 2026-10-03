from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from agentic_django.models import AgentRun, AgentSession


@pytest.mark.django_db()
def test_run_validation_rejects_another_owners_session(user: Any) -> None:
    other = get_user_model().objects.create_user(username="other-owner")
    session = AgentSession.objects.create(session_key="private", owner=other)
    run = AgentRun(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    with pytest.raises(ValidationError, match="session"):
        run.full_clean()


@pytest.mark.django_db()
def test_session_owner_change_preserves_linked_run_ownership(user: Any) -> None:
    other = get_user_model().objects.create_user(username="other-owner")
    session = AgentSession.objects.create(session_key="private", owner=user)
    AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    session.owner = other
    with pytest.raises(ValidationError, match="owner"):
        session.full_clean()


@pytest.mark.django_db()
def test_empty_session_can_change_owner(user: Any) -> None:
    other = get_user_model().objects.create_user(username="other-owner")
    session = AgentSession.objects.create(session_key="empty", owner=user)
    session.owner = other
    session.full_clean()
    session.save()
    session.refresh_from_db()
    assert session.owner == other


@pytest.mark.django_db()
def test_only_one_running_run_per_session(user: Any) -> None:
    from django.db import IntegrityError, transaction

    session = AgentSession.objects.create(session_key="exclusive", owner=user)
    AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        input_payload="first",
        status=AgentRun.Status.RUNNING,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AgentRun.objects.create(
            session=session,
            owner=user,
            agent_key="default",
            input_payload="second",
            status=AgentRun.Status.RUNNING,
        )
