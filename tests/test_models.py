from __future__ import annotations

from typing import Any

import pytest

from agentic_django.models import AgentRun, AgentSession


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
