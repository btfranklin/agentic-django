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
    AgentRun.objects.filter(id=run_old.id).update(
        updated_at=old_time,
        finished_at=old_time,
    )
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
    session_with_item.items.create(
        sequence=1,
        payload={"role": "user", "content": "hi"},
    )

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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("new_work", ["run", "item", "touch"])
def test_cleanup_rechecks_session_after_concurrent_reuse(
    user: Any, monkeypatch: pytest.MonkeyPatch, new_work: str
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from io import StringIO

    from django.db import close_old_connections
    from django.db.models import QuerySet

    session = AgentSession.objects.create(session_key="reused", owner=user)
    old_time = timezone.now() - timedelta(days=2)
    AgentSession.objects.filter(pk=session.pk).update(updated_at=old_time)
    original_update = QuerySet.update
    reused = False

    def reuse_session() -> None:
        close_old_connections()
        try:
            if new_work == "run":
                AgentRun.objects.create(
                    session_id=session.pk,
                    owner_id=user.pk,
                    agent_key="default",
                    input_payload="new work",
                )
            elif new_work == "item":
                session.items.create(sequence=1, payload={"content": "new history"})
            else:
                AgentSession.objects.filter(pk=session.pk).update(
                    updated_at=timezone.now()
                )
        finally:
            close_old_connections()

    def update_after_reuse(queryset: Any, **kwargs: Any) -> int:
        nonlocal reused
        if queryset.model is AgentSession and "id" in kwargs and not reused:
            reused = True
            # Commit work on another connection after candidate selection.
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(reuse_session).result(timeout=10)
        return original_update(queryset, **kwargs)

    monkeypatch.setattr(QuerySet, "update", update_after_reuse)
    output = StringIO()
    call_command("agentic_django_cleanup", sessions_days=1, stdout=output)

    assert reused
    assert AgentSession.objects.filter(pk=session.pk).exists()
    assert "Deleted 0 sessions." in output.getvalue()
    if new_work == "run":
        assert session.runs.count() == 1
    elif new_work == "item":
        assert session.items.count() == 1


@pytest.mark.django_db()
@pytest.mark.parametrize("status", [AgentRun.Status.PENDING, AgentRun.Status.RUNNING])
def test_nonempty_cleanup_keeps_sessions_with_active_runs(
    user: Any, status: str
) -> None:
    session = AgentSession.objects.create(session_key="active", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        input_payload="work",
        status=status,
    )
    old_time = timezone.now() - timedelta(days=2)
    AgentSession.objects.filter(pk=session.pk).update(updated_at=old_time)

    call_command(
        "agentic_django_cleanup", sessions_days=1, sessions_require_empty=False
    )

    assert AgentSession.objects.filter(pk=session.pk).exists()
    assert AgentRun.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db()
def test_nonempty_cleanup_deletes_terminal_session_and_counts_only_sessions(
    user: Any,
) -> None:
    from io import StringIO

    session = AgentSession.objects.create(session_key="terminal", owner=user)
    AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        input_payload="work",
        status=AgentRun.Status.COMPLETED,
    )
    session.items.create(sequence=1, payload={"content": "old history"})
    AgentSession.objects.filter(pk=session.pk).update(
        updated_at=timezone.now() - timedelta(days=2)
    )
    output = StringIO()

    call_command(
        "agentic_django_cleanup",
        sessions_days=1,
        sessions_require_empty=False,
        stdout=output,
    )

    assert not AgentSession.objects.filter(pk=session.pk).exists()
    assert "Deleted 1 sessions." in output.getvalue()


@pytest.mark.django_db()
def test_cleanup_rechecks_run_status_after_candidate_selection(
    user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db.models import QuerySet

    session = AgentSession.objects.create(session_key="requeued", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        input_payload="work",
        status=AgentRun.Status.COMPLETED,
    )
    AgentRun.objects.filter(pk=run.pk).update(
        updated_at=timezone.now() - timedelta(days=2)
    )
    original_update = QuerySet.update
    requeued = False

    def update_after_requeue(queryset: Any, **kwargs: Any) -> int:
        nonlocal requeued
        if queryset.model is AgentRun and "id" in kwargs and not requeued:
            requeued = True
            AgentRun.objects.filter(pk=run.pk).update(status=AgentRun.Status.PENDING)
        return original_update(queryset, **kwargs)

    monkeypatch.setattr(QuerySet, "update", update_after_requeue)
    call_command("agentic_django_cleanup", runs_days=1)

    run.refresh_from_db()
    assert run.status == AgentRun.Status.PENDING
