from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from agentic_django.models import AgentEvent, AgentRun, AgentSession


@pytest.mark.django_db()
def test_cleanup_command_prunes_events(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.RUNNING,
        input_payload="hello",
    )
    event_old = AgentEvent.objects.create(
        run=run,
        sequence=1,
        event_type="tool_called",
        payload={"ok": True},
    )
    event_new = AgentEvent.objects.create(
        run=run,
        sequence=2,
        event_type="tool_called",
        payload={"ok": True},
    )
    old_time = timezone.now() - timedelta(days=2)
    AgentEvent.objects.filter(id=event_old.id).update(created_at=old_time)

    with override_settings(AGENTIC_DJANGO_CLEANUP_POLICY={"events_days": 1}):
        call_command("agentic_django_cleanup")

    assert not AgentEvent.objects.filter(id=event_old.id).exists()
    assert AgentEvent.objects.filter(id=event_new.id).exists()
    run.refresh_from_db()
    assert run.status == AgentRun.Status.RUNNING


@pytest.mark.django_db()
def test_cleanup_command_prunes_runs(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run_old = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.COMPLETED,
        input_payload="hello",
        finished_at=timezone.now(),
    )
    run_new = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.COMPLETED,
        input_payload="hello",
        finished_at=timezone.now(),
    )
    run_running = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.RUNNING,
        input_payload="hello",
    )
    old_time = timezone.now() - timedelta(days=2)
    AgentRun.objects.filter(id=run_old.id).update(updated_at=old_time, finished_at=old_time)
    AgentRun.objects.filter(id=run_running.id).update(updated_at=old_time)

    with override_settings(AGENTIC_DJANGO_CLEANUP_POLICY={"runs_days": 1}):
        call_command("agentic_django_cleanup")

    assert not AgentRun.objects.filter(id=run_old.id).exists()
    assert AgentRun.objects.filter(id=run_new.id).exists()
    assert AgentRun.objects.filter(id=run_running.id).exists()


@pytest.mark.django_db()
def test_cleanup_command_prunes_empty_sessions(user: Any) -> None:
    session_old = AgentSession.objects.create(session_key="old", owner=user)
    session_with_item = AgentSession.objects.create(session_key="with-item", owner=user)
    session_with_item.items.create(sequence=1, payload={"role": "user", "content": "hi"})

    old_time = timezone.now() - timedelta(days=2)
    AgentSession.objects.filter(id=session_old.id).update(updated_at=old_time)
    AgentSession.objects.filter(id=session_with_item.id).update(updated_at=old_time)

    with override_settings(AGENTIC_DJANGO_CLEANUP_POLICY={"sessions_days": 1}):
        call_command("agentic_django_cleanup")

    assert not AgentSession.objects.filter(id=session_old.id).exists()
    assert AgentSession.objects.filter(id=session_with_item.id).exists()


@pytest.mark.django_db()
def test_recover_runs_command_fails_running(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.RUNNING,
        input_payload="hello",
    )

    call_command("agentic_django_recover_runs", mode="fail")

    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.error == "Server restart"
