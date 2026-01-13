from __future__ import annotations

from typing import Any

import pytest

from agentic_django.models import AgentRun, AgentSession


@pytest.mark.django_db()
def test_agent_run_status_helpers(user: Any) -> None:
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
    )

    run.mark_running()
    run.refresh_from_db()
    assert run.status == AgentRun.Status.RUNNING
    assert run.started_at is not None

    run.mark_completed()
    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.finished_at is not None

    run.mark_failed("boom")
    run.refresh_from_db()
    assert run.status == AgentRun.Status.FAILED
    assert run.error == "boom"
