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


@pytest.mark.django_db(transaction=True)
def test_queue_failure_releases_unsent_batch_for_retry(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    runs = [
        AgentRun.objects.create(
            session=AgentSession.objects.create(session_key=str(i), owner=user),
            owner=user, agent_key="default", input_payload="hi",
        )
        for i in range(3)
    ]
    sent = []

    def enqueue(task: Any, run_id: str) -> DummyTask:
        if len(sent) == 1:
            raise RuntimeError("queue unavailable")
        sent.append(run_id)
        return DummyTask("accepted")

    monkeypatch.setattr("agentic_django.services._enqueue_task", enqueue)
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=3):
        with pytest.raises(RuntimeError, match="queue unavailable"):
            dispatch_pending_runs()
        assert AgentRun.objects.get(id=runs[0].id).task_id == "accepted"
        assert list(AgentRun.objects.exclude(id=runs[0].id).values_list(
            "task_id", flat=True
        )) == ["", ""]
        monkeypatch.setattr(
            "agentic_django.services._enqueue_task",
            lambda *args: DummyTask("retried"),
        )
        assert dispatch_pending_runs() == 2


@pytest.mark.django_db(transaction=True)
def test_initial_queue_failure_can_be_retried(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    from agentic_django.services import enqueue_agent_run

    session = AgentSession.objects.create(session_key="retry", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )

    def unavailable(*args: Any) -> None:
        raise RuntimeError("offline")

    monkeypatch.setattr("agentic_django.services._enqueue_task", unavailable)
    with pytest.raises(RuntimeError):
        enqueue_agent_run(str(run.id))
    run.refresh_from_db()
    assert run.task_id == ""
    monkeypatch.setattr(
        "agentic_django.services._enqueue_task", lambda *args: DummyTask("retry")
    )
    assert dispatch_pending_runs() == 1


@pytest.mark.django_db(transaction=True)
def test_immediate_rejection_does_not_restore_obsolete_task_id(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    from agentic_django.services import enqueue_agent_run

    session = AgentSession.objects.create(session_key="busy", owner=user)
    AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi",
        status=AgentRun.Status.RUNNING,
    )
    pending = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="next"
    )

    def immediate(task: Any, run_id: str) -> DummyTask:
        execute_run(run_id)
        return DummyTask("already-finished-task")

    monkeypatch.setattr("agentic_django.services._enqueue_task", immediate)
    enqueue_agent_run(str(pending.id))
    pending.refresh_from_db()
    assert pending.status == AgentRun.Status.PENDING
    assert pending.task_id == ""


@pytest.mark.django_db()
@pytest.mark.parametrize("signal_name", ["agent_run_started", "agent_run_completed"])
def test_notification_failure_does_not_fail_successful_run(
    monkeypatch: pytest.MonkeyPatch, user: Any, signal_name: str
) -> None:
    from agentic_django import signals

    session = AgentSession.objects.create(session_key="signals", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )
    received = []

    def broken(sender: Any, **kwargs: Any) -> None:
        raise RuntimeError("notification failed")

    def healthy(sender: Any, **kwargs: Any) -> None:
        received.append(kwargs["run"].id)

    async def runner(*args: Any, **kwargs: Any) -> DummyResult:
        return DummyResult()

    signal = getattr(signals, signal_name)
    signal.connect(broken, weak=False)
    signal.connect(healthy, weak=False)
    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", runner)
    try:
        execute_run(str(run.id))
    finally:
        signal.disconnect(broken)
        signal.disconnect(healthy)
    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.final_output == {"ok": True}
    assert received == [run.id]


@pytest.mark.django_db()
def test_serializer_setup_failure_releases_run_slot(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    session = AgentSession.objects.create(session_key="setup", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )

    def broken() -> None:
        raise RuntimeError("setup failed")

    dispatched = []
    monkeypatch.setattr("agentic_django.services._get_serializer", broken)
    monkeypatch.setattr(
        "agentic_django.services.dispatch_pending_runs", lambda: dispatched.append(True)
    )
    with pytest.raises(RuntimeError, match="setup failed"):
        execute_run(str(run.id))
    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.finished_at is not None
    assert dispatched == [True]


@pytest.mark.django_db()
def test_failure_notification_preserves_original_error(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    from agentic_django.signals import agent_run_failed

    session = AgentSession.objects.create(session_key="failure", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )

    def broken(sender: Any, **kwargs: Any) -> None:
        raise RuntimeError("notification failed")

    def broken_agent(key: str) -> None:
        raise ValueError("original failure")

    monkeypatch.setattr("agentic_django.services.get_agent", broken_agent)
    agent_run_failed.connect(broken, weak=False)
    try:
        with pytest.raises(ValueError, match="original failure"):
            execute_run(str(run.id))
    finally:
        agent_run_failed.disconnect(broken)
    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
