from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import CancelledError
from types import SimpleNamespace
from typing import Any

import pytest
from agents import Agent, Model, RunConfig, Runner
from agents.items import ModelResponse, TResponseStreamEvent
from agents.result import RunResultStreaming
from django.test import override_settings
from django.utils import timezone

from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.services import (
    _build_run_options,
    _persist_event,
    submit_agent_run,
    dispatch_pending_runs,
    execute_run,
)
from agentic_django.signals import (
    agent_run_completed,
    agent_run_event,
    agent_run_failed,
)


class DummyResult:
    def __init__(self) -> None:
        self.final_output = {"ok": True}
        self.raw_responses = [{"id": "resp"}]
        self.last_response_id = "resp"
        self.released = False
        self.interruptions: list[Any] = []

    def release_agents(self) -> None:
        self.released = True


class DummyTaskResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


@pytest.mark.django_db()
@pytest.mark.parametrize("events", [False, True])
def test_cancelled_sdk_model_marks_the_run_failed(
    monkeypatch: pytest.MonkeyPatch, user: Any, events: bool,
) -> None:
    class CancelModel(Model):
        async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
            raise asyncio.CancelledError("model task cancelled")

        async def stream_response(
            self, *args: Any, **kwargs: Any,
        ) -> AsyncIterator[TResponseStreamEvent]:
            raise asyncio.CancelledError("model task cancelled")
            yield

    session = AgentSession.objects.create(session_key="cancelled", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
        task_id="cancelled-task",
    )
    model = CancelModel()
    monkeypatch.setattr(
        "agentic_django.services.get_agent",
        lambda key: Agent(name="cancel", model=model),
    )
    results: list[RunResultStreaming] = []
    original_runner = Runner.run_streamed

    def capture(*args: Any, **kwargs: Any) -> RunResultStreaming:
        result = original_runner(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr("agentic_django.services.Runner.run_streamed", capture)
    completed: list[Any] = []
    failed: list[Any] = []

    def completed_receiver(sender: Any, **kwargs: Any) -> None:
        completed.append(kwargs["run"].pk)

    def failed_receiver(sender: Any, **kwargs: Any) -> None:
        failed.append(kwargs["run"].pk)

    agent_run_completed.connect(completed_receiver, weak=False)
    agent_run_failed.connect(failed_receiver, weak=False)
    try:
        with override_settings(
            AGENTIC_DJANGO_ENABLE_EVENTS=events,
            AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS={
                "run_config": RunConfig(tracing_disabled=True),
            },
        ):
            expected_error = RuntimeError if events else CancelledError
            with pytest.raises(expected_error):
                execute_run(str(run.pk))
    finally:
        agent_run_completed.disconnect(completed_receiver)
        agent_run_failed.disconnect(failed_receiver)
    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.finished_at is not None
    assert run.task_id == ""
    assert completed == []
    assert failed == [run.pk]
    if events:
        assert len(results) == 1
        task = results[0].run_loop_task
        assert task is not None and task.cancelled()
        assert results[0].current_agent is None


@pytest.mark.django_db()
@pytest.mark.parametrize("successful", [False, True])
def test_followup_queue_failure_preserves_current_run_outcome(
    monkeypatch: pytest.MonkeyPatch, user: Any, successful: bool,
) -> None:
    session = AgentSession.objects.create(session_key="queue-error", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )

    async def runner(*args: Any, **kwargs: Any) -> DummyResult:
        if not successful:
            raise ValueError("original model error")
        return DummyResult()

    def unavailable() -> None:
        raise OSError("queue unavailable")

    monkeypatch.setattr("agentic_django.services.Runner.run", runner)
    monkeypatch.setattr("agentic_django.services.dispatch_pending_runs", unavailable)
    if successful:
        execute_run(str(run.pk))
    else:
        with pytest.raises(ValueError, match="original model error"):
            execute_run(str(run.pk))
    run.refresh_from_db()
    assert run.status == (
        AgentRun.Status.COMPLETED if successful else AgentRun.Status.FAILED
    )
    assert run.task_id == ""


@pytest.mark.django_db(transaction=True)
def test_immediate_backend_completes_a_large_backlog(
    monkeypatch: pytest.MonkeyPatch, user: Any,
) -> None:
    session = AgentSession.objects.create(session_key="immediate-backlog", owner=user)
    AgentRun.objects.bulk_create([
        AgentRun(
            session=session, owner=user, agent_key="default", input_payload="hello",
        )
        for _ in range(120)
    ])

    async def runner(*args: Any, **kwargs: Any) -> DummyResult:
        return DummyResult()

    monkeypatch.setattr("agentic_django.services.Runner.run", runner)
    with override_settings(
        AGENTIC_DJANGO_CONCURRENCY_LIMIT=1,
        TASKS={"default": {
            "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
        }},
    ):
        dispatch_pending_runs()
    assert AgentRun.objects.filter(status=AgentRun.Status.COMPLETED).count() == 120
    assert not AgentRun.objects.exclude(task_id="").exists()


@pytest.mark.django_db()
@pytest.mark.parametrize("events", [False, True])
def test_pending_approval_is_failed_and_result_references_are_released(
    monkeypatch: pytest.MonkeyPatch, user: Any, events: bool,
) -> None:
    from agentic_django.signals import agent_run_completed

    session = AgentSession.objects.create(session_key="approval", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    result = DummyResult()
    result.interruptions = [object()]
    result.final_output = None
    completed = []

    def receiver(sender: Any, **kwargs: Any) -> None:
        completed.append(kwargs["run"].pk)

    async def runner(*args: Any, **kwargs: Any) -> DummyResult:
        return result

    monkeypatch.setattr("agentic_django.services.Runner.run", runner)
    monkeypatch.setattr("agentic_django.services._run_with_events", lambda **kw: result)
    agent_run_completed.connect(receiver, weak=False)
    try:
        with override_settings(AGENTIC_DJANGO_ENABLE_EVENTS=events):
            with pytest.raises(ValueError, match="approval"):
                execute_run(str(run.pk))
    finally:
        agent_run_completed.disconnect(receiver)
    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.finished_at is not None
    assert run.task_id == ""
    assert run.final_output is None
    assert completed == []
    assert result.released


def _replace_run_task(monkeypatch: pytest.MonkeyPatch, enqueue: Any) -> None:
    monkeypatch.setattr(
        "agentic_django.tasks.run_agent_task",
        SimpleNamespace(enqueue=enqueue),
    )


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
        task_id="task-success",
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
    assert run.task_id == ""
    assert run.started_at is not None
    assert run.finished_at is not None


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
        task_id="task-failure",
    )

    async def failing_run(*args: Any, **kwargs: Any) -> DummyResult:
        raise RuntimeError("boom")

    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", failing_run)

    with pytest.raises(RuntimeError):
        execute_run(str(run.id))

    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.error == "The agent run failed. Contact support with the run ID."
    assert run.task_id == ""
    assert run.started_at is not None
    assert run.finished_at is not None


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
    assert run.error == "The agent run failed. Contact support with the run ID."


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

    def fake_enqueue(run_id: str) -> DummyTaskResult:
        return DummyTaskResult(task_id="task-1")

    _replace_run_task(monkeypatch, fake_enqueue)
    monkeypatch.setattr("agentic_django.services.get_concurrency_limit", lambda: 1)

    count = dispatch_pending_runs()
    assert count == 1

    run_ids = {run.id for run in runs}
    updated = AgentRun.objects.filter(id__in=run_ids, task_id="task-1").count()
    assert updated == 1


@pytest.mark.django_db()
def test_persist_event_notifies_receivers_after_save(user: Any) -> None:
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
        assert sender is AgentEvent
        assert AgentEvent.objects.get(pk=kwargs["event"].pk).payload == event.payload
        received.append(kwargs)

    def broken_receiver(sender: Any, **kwargs: Any) -> None:
        raise RuntimeError("notification failed")

    agent_run_event.connect(broken_receiver, weak=False)
    agent_run_event.connect(receiver, weak=False)
    try:
        _persist_event(run, event)
    finally:
        agent_run_event.disconnect(receiver)
        agent_run_event.disconnect(broken_receiver)

    assert received[0]["run"] == run
    assert received[0]["event"] == event
    assert received[0]["sequence"] == 1
    assert received[0]["event_type"] == "tool_called"
    assert received[0]["payload"] == event.payload


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
    _replace_run_task(monkeypatch, lambda run_id: dispatched.append(run_id))
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
        first.status = AgentRun.Status.COMPLETED
        first.finished_at = timezone.now()
        first.save(update_fields=["status", "finished_at", "updated_at"])
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

    def enqueue(run_id: str) -> DummyTaskResult:
        sent.append(run_id)
        return DummyTaskResult(run_id)

    _replace_run_task(monkeypatch, enqueue)
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

    def enqueue(run_id: str) -> DummyTaskResult:
        assert not transaction.get_connection().in_atomic_block
        assert AgentRun.objects.filter(id=run_id).exists()
        sent.append(run_id)
        return DummyTaskResult("accepted")

    _replace_run_task(monkeypatch, enqueue)
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

    def enqueue(run_id: str) -> DummyTaskResult:
        if len(sent) == 1:
            raise RuntimeError("queue unavailable")
        sent.append(run_id)
        return DummyTaskResult("accepted")

    _replace_run_task(monkeypatch, enqueue)
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=3):
        with pytest.raises(RuntimeError, match="queue unavailable"):
            dispatch_pending_runs()
        assert AgentRun.objects.get(id=runs[0].id).task_id == "accepted"
        assert list(AgentRun.objects.exclude(id=runs[0].id).values_list(
            "task_id", flat=True
        )) == ["", ""]
        _replace_run_task(
            monkeypatch,
            lambda run_id: DummyTaskResult("retried"),
        )
        assert dispatch_pending_runs() == 2


@pytest.mark.django_db(transaction=True)
def test_queue_failure_releases_nested_immediate_submissions(
    monkeypatch: pytest.MonkeyPatch, user: Any,
) -> None:
    from agentic_django.services import enqueue_agent_run

    runs = [
        AgentRun.objects.create(
            session=AgentSession.objects.create(session_key=f"nested-{i}", owner=user),
            owner=user, agent_key="default", input_payload="hello",
        )
        for i in range(3)
    ]

    def enqueue(run_id: str) -> DummyTaskResult:
        if run_id != str(runs[0].pk):
            raise OSError("queue unavailable")
        AgentRun.objects.filter(pk=run_id).update(
            status=AgentRun.Status.COMPLETED, task_id="",
        )
        assert dispatch_pending_runs() == 2
        return DummyTaskResult("completed-task")

    _replace_run_task(monkeypatch, enqueue)
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=3):
        with pytest.raises(OSError, match="queue unavailable"):
            enqueue_agent_run(str(runs[0].pk))
        assert not AgentRun.objects.exclude(task_id="").exists()
        _replace_run_task(monkeypatch, lambda run_id: DummyTaskResult("retried"))
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

    def unavailable(run_id: str) -> None:
        raise RuntimeError("offline")

    _replace_run_task(monkeypatch, unavailable)
    with pytest.raises(RuntimeError):
        enqueue_agent_run(str(run.id))
    run.refresh_from_db()
    assert run.task_id == ""
    _replace_run_task(monkeypatch, lambda run_id: DummyTaskResult("retry"))
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

    def immediate(run_id: str) -> DummyTaskResult:
        execute_run(run_id)
        return DummyTaskResult("already-finished-task")

    _replace_run_task(monkeypatch, immediate)
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


@pytest.mark.django_db(transaction=True)
def test_recovery_leaves_pending_reservations_unless_requested(user: Any) -> None:
    from agentic_django.services import recover_stuck_runs

    session = AgentSession.objects.create(session_key="reserved", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi",
        task_id="queued:abandoned",
    )
    assert recover_stuck_runs("fail") == 0
    run.refresh_from_db()
    assert run.status == AgentRun.Status.PENDING
    assert run.task_id == "queued:abandoned"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["fail", "requeue"])
@pytest.mark.parametrize("task_id", ["queued:abandoned", "accepted-task-id"])
def test_recovery_command_handles_abandoned_pending_reservations(
    monkeypatch: pytest.MonkeyPatch, user: Any, mode: str, task_id: str
) -> None:
    from django.core.management import call_command

    session = AgentSession.objects.create(session_key="reserved", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi",
        task_id=task_id,
    )
    sent = []

    def enqueue(run_id: str) -> DummyTaskResult:
        sent.append(run_id)
        return DummyTaskResult("replacement")

    _replace_run_task(monkeypatch, enqueue)
    call_command("agentic_django_recover_runs", mode=mode, include_pending=True)
    run.refresh_from_db()
    if mode == "fail":
        assert run.status == AgentRun.Status.FAILED
        assert run.task_id == ""
        assert run.finished_at is not None
        assert sent == []
    else:
        assert run.status == AgentRun.Status.PENDING
        assert run.task_id == "replacement"
        assert sent == [str(run.id)]


@pytest.mark.django_db(transaction=True)
def test_dispatch_limits_backlog_rows_read(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    session = AgentSession.objects.create(session_key="backlog", owner=user)
    AgentRun.objects.bulk_create([
        AgentRun(session=session, owner=user, agent_key="default", input_payload="hi")
        for _ in range(100)
    ])
    _replace_run_task(monkeypatch, lambda run_id: DummyTaskResult("accepted"))
    with override_settings(AGENTIC_DJANGO_CONCURRENCY_LIMIT=2):
        with CaptureQueriesContext(connection) as queries:
            assert dispatch_pending_runs() == 1
    # A session with a large backlog must not cause all pending rows to load.
    pending_selects = [
        query["sql"] for query in queries.captured_queries
        if query["sql"].startswith("SELECT") and '"task_id" = ' in query["sql"]
    ]
    assert pending_selects
    assert all("LIMIT 1" in query for query in pending_selects)


@pytest.mark.django_db()
def test_pending_recovery_preserves_unreserved_work(user: Any) -> None:
    from agentic_django.services import recover_stuck_runs

    session = AgentSession.objects.create(session_key="unreserved", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi",
    )
    assert recover_stuck_runs("fail", include_pending=True) == 0
    run.refresh_from_db()
    assert run.status == AgentRun.Status.PENDING
    assert run.task_id == ""


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('backend', [
    'agentic_django.sessions.DatabaseSession', 'tests.support.RecordingSession',
])
def test_submit_run_initializes_backend_and_notifies_once(
    user: Any, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    from agentic_django.signals import agent_session_created
    from tests.support import RecordingSession

    created = []
    sent = []
    RecordingSession.called = False

    def receiver(sender: Any, **kwargs: Any) -> None:
        created.append(kwargs['session'].pk)

    def enqueue(run_id: str) -> DummyTaskResult:
        from django.db import connection
        assert not connection.in_atomic_block
        assert AgentRun.objects.filter(pk=run_id).exists()
        sent.append(run_id)
        return DummyTaskResult('submitted')

    _replace_run_task(monkeypatch, enqueue)
    metadata = {'context': {'topic': 'test'}, 'run_options': {'max_turns': 2}}
    agent_session_created.connect(receiver, weak=False)
    try:
        with override_settings(AGENTIC_DJANGO_SESSION_BACKEND=backend):
            run = submit_agent_run(
                owner=user, session_key='submission', agent_key='default',
                input_payload='hello', metadata=metadata,
            )
    finally:
        agent_session_created.disconnect(receiver)

    run.refresh_from_db()
    assert run.owner == run.session.owner == user
    assert run.input_payload == 'hello'
    assert run.metadata == metadata
    assert run.status == AgentRun.Status.PENDING
    assert run.task_id == 'submitted'
    assert created == [run.session_id]
    assert sent == [str(run.pk)]
    if backend == 'tests.support.RecordingSession':
        assert RecordingSession.called


@pytest.mark.django_db(transaction=True)
def test_submit_run_obeys_outer_transaction_commit_and_rollback(
    user: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.db import transaction

    sent = []

    def enqueue(run_id: str) -> DummyTaskResult:
        sent.append(run_id)
        return DummyTaskResult('submitted')

    _replace_run_task(monkeypatch, enqueue)
    with transaction.atomic():
        run = submit_agent_run(
            owner=user, session_key='committed', agent_key='default',
            input_payload='hello',
        )
        assert sent == []
    assert sent == [str(run.pk)]

    with pytest.raises(RuntimeError, match='rollback'), transaction.atomic():
        submit_agent_run(
            owner=user, session_key='rolled-back', agent_key='default',
            input_payload='hello',
        )
        raise RuntimeError('rollback')
    assert sent == [str(run.pk)]
    assert not AgentSession.objects.filter(session_key='rolled-back').exists()
    assert AgentRun.objects.count() == 1


@pytest.mark.django_db()
def test_submit_run_backend_failure_rolls_back_local_records(
    user: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_backend(session_key: str, owner: Any) -> None:
        AgentSession.objects.create(session_key=session_key, owner=owner)
        raise RuntimeError('backend failed')

    monkeypatch.setattr('agentic_django.services.get_session', failing_backend)
    with pytest.raises(RuntimeError, match='backend failed'):
        submit_agent_run(
            owner=user, session_key='failed', agent_key='default', input_payload='hi',
        )
    assert not AgentSession.objects.exists()
    assert not AgentRun.objects.exists()


@pytest.mark.django_db()
def test_submit_run_reuses_only_the_owners_session(user: Any) -> None:
    from datetime import timedelta
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username='other-submitter')
    own_session = AgentSession.objects.create(owner=user, session_key='shared-key')
    other_session = AgentSession.objects.create(owner=other, session_key='shared-key')
    old_time = timezone.now() - timedelta(days=90)
    AgentSession.objects.update(updated_at=old_time)
    own_session.items.create(sequence=1, payload={'content': 'existing history'})

    run = submit_agent_run(
        owner=user, session_key='shared-key', agent_key='default', input_payload='hi',
    )

    own_session.refresh_from_db()
    other_session.refresh_from_db()
    assert run.session_id == own_session.pk
    assert own_session.updated_at > old_time
    assert own_session.items.get().payload == {'content': 'existing history'}
    assert other_session.updated_at == old_time
    assert not other_session.runs.exists()
