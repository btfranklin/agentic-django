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
