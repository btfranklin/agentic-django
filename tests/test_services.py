from __future__ import annotations

from typing import Any

import pytest
from django.test import override_settings

from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.services import (
    _build_run_options,
    _extract_task_id,
    _send_event_signals,
    dispatch_pending_runs,
    execute_run,
)
from agentic_django.signals import agent_run_event


class DummyResult:
    def __init__(self) -> None:
        self.final_output = {"ok": True}
        self.raw_responses = [{"id": "resp"}]
        self.last_response_id = "resp"
        self.released = False

    def release_agents(self) -> None:
        self.released = True


class DummyTask:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


@pytest.mark.django_db()
def test_build_run_options_merges_settings(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hi",
        metadata={"run_options": {"max_turns": 2}},
    )
    with override_settings(AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS={"temperature": 0.2}):
        options = _build_run_options(run)
    assert options == {"temperature": 0.2, "max_turns": 2}


@pytest.mark.django_db()
def test_execute_run_success(monkeypatch: pytest.MonkeyPatch, user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
        metadata={},
    )

    async def fake_run(*args: Any, **kwargs: Any) -> DummyResult:
        return DummyResult()

    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", fake_run)

    execute_run(str(run.id))

    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.final_output == {"ok": True}
    assert run.raw_responses == [{"id": "resp"}]
    assert run.last_response_id == "resp"
    assert run.error == ""


@pytest.mark.django_db()
def test_execute_run_failure(monkeypatch: pytest.MonkeyPatch, user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
        metadata={},
    )

    async def failing_run(*args: Any, **kwargs: Any) -> DummyResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", failing_run)

    with pytest.raises(RuntimeError):
        execute_run(str(run.id))

    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert "RuntimeError" in run.error


@pytest.mark.django_db()
def test_execute_run_failure_sanitized(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
        metadata={},
    )

    async def failing_run(*args: Any, **kwargs: Any) -> DummyResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", failing_run)

    with override_settings(DEBUG=False):
        with pytest.raises(RuntimeError):
            execute_run(str(run.id))

    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert "Traceback" not in run.error
    assert run.error == "RuntimeError: boom"


@pytest.mark.django_db(transaction=True)
def test_dispatch_pending_runs(monkeypatch: pytest.MonkeyPatch, user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    runs = [
        AgentRun.objects.create(
            session=session,
            owner=user,
            agent_key="default",
            status=AgentRun.Status.PENDING,
            input_payload="hello",
            metadata={},
        )
        for _ in range(2)
    ]

    def fake_enqueue(*args: Any, **kwargs: Any) -> DummyTask:
        return DummyTask(task_id="task-1")

    monkeypatch.setattr("agentic_django.services._enqueue_task", fake_enqueue)
    monkeypatch.setattr("agentic_django.services.get_concurrency_limit", lambda: 1)

    count = dispatch_pending_runs()
    assert count == 1

    run_ids = {run.id for run in runs}
    updated = AgentRun.objects.filter(id__in=run_ids, task_id="task-1").count()
    assert updated == 1


def test_extract_task_id() -> None:
    assert _extract_task_id(DummyTask("abc")) == "abc"
    assert _extract_task_id(type("Obj", (), {"task_id": "def"})()) == "def"
    assert _extract_task_id(object()) is None


@pytest.mark.django_db()
def test_send_event_signals(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.RUNNING,
        input_payload="hello",
    )
    event = AgentEvent(
        run=run,
        sequence=1,
        event_type="tool_called",
        payload={"type": "run_item_stream_event"},
    )

    received: list[dict[str, Any]] = []

    def receiver(sender: Any, **kwargs: Any) -> None:
        received.append(kwargs)

    agent_run_event.connect(receiver, weak=False)
    try:
        _send_event_signals(run, [event])
    finally:
        agent_run_event.disconnect(receiver)

    assert received
    assert received[0]["event_type"] == "tool_called"


@pytest.mark.django_db(transaction=True)
def test_dispatch_preserves_another_workers_active_run(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    session = AgentSession.objects.create(session_key="active", owner=user)
    active = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi",
        status=AgentRun.Status.RUNNING, task_id="active-worker",
    )
    monkeypatch.setattr("agentic_django.services.get_concurrency_limit", lambda: 1)
    dispatched = []
    monkeypatch.setattr(
        "agentic_django.services._enqueue_task",
        lambda *args: dispatched.append(args),
    )
    assert dispatch_pending_runs() == 0
    execute_run(str(active.id))
    active.refresh_from_db()
    assert active.status == AgentRun.Status.RUNNING
    assert active.task_id == "active-worker"
    assert dispatched == []


@pytest.mark.django_db(transaction=True)
def test_session_reservation_blocks_overlap_but_allows_other_sessions(
    user: Any,
) -> None:
    from agentic_django.services import _reserve_run_slot

    session = AgentSession.objects.create(session_key="conversation", owner=user)
    other = AgentSession.objects.create(session_key="other", owner=user)
    first, second, independent = [
        AgentRun.objects.create(
            session=target, owner=user, agent_key="default", input_payload="hello"
        )
        for target in (session, session, other)
    ]
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=3):
        assert _reserve_run_slot(first)
        assert not _reserve_run_slot(second)
        assert _reserve_run_slot(independent)
        first.mark_completed()
        assert _reserve_run_slot(second)


@pytest.mark.django_db(transaction=True)
def test_dispatch_selects_distinct_idle_sessions(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    active = AgentSession.objects.create(session_key="active", owner=user)
    idle = AgentSession.objects.create(session_key="idle", owner=user)
    other = AgentSession.objects.create(session_key="other", owner=user)
    AgentRun.objects.create(
        session=active, owner=user, agent_key="default", input_payload="hi",
        status=AgentRun.Status.RUNNING,
    )
    pending = [
        AgentRun.objects.create(
            session=target, owner=user, agent_key="default", input_payload="hi"
        )
        for target in (active, idle, idle, other)
    ]
    sent = []

    def enqueue(task: Any, run_id: str) -> DummyTask:
        sent.append(run_id)
        return DummyTask(run_id)

    monkeypatch.setattr("agentic_django.services._enqueue_task", enqueue)
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=3):
        assert dispatch_pending_runs() == 2
    assert sent == [str(pending[1].id), str(pending[3].id)]


@pytest.mark.django_db(transaction=True)
def test_initial_enqueue_waits_for_commit_and_is_discarded_on_rollback(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    from django.db import transaction
    from agentic_django.services import enqueue_agent_run

    sent = []

    def enqueue(task: Any, run_id: str) -> DummyTask:
        assert not transaction.get_connection().in_atomic_block
        assert AgentRun.objects.filter(id=run_id).exists()
        sent.append(run_id)
        return DummyTask("accepted")

    monkeypatch.setattr("agentic_django.services._enqueue_task", enqueue)
    session = AgentSession.objects.create(session_key="commit", owner=user)
    with transaction.atomic():
        run = AgentRun.objects.create(
            session=session, owner=user, agent_key="default", input_payload="hi"
        )
        enqueue_agent_run(str(run.id))
        assert not sent
    assert sent == [str(run.id)]
    run.refresh_from_db()
    assert run.task_id == "accepted"

    with pytest.raises(RuntimeError), transaction.atomic():
        rolled_back = AgentRun.objects.create(
            session=session, owner=user, agent_key="default", input_payload="hi"
        )
        enqueue_agent_run(str(rolled_back.id))
        raise RuntimeError("rollback")
    assert sent == [str(run.id)]
    assert not AgentRun.objects.filter(id=rolled_back.id).exists()
