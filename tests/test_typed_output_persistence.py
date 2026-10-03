from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel

from agentic_django.models import AgentRun, AgentSession
from agentic_django.services import execute_run


class TypedOutput(BaseModel):
    day: date
    instant: datetime
    amount: Decimal
    identifier: UUID
    optional: str | None


@pytest.mark.django_db()
def test_execute_run_persists_typed_output(
    monkeypatch: pytest.MonkeyPatch, user: Any
) -> None:
    session = AgentSession.objects.create(session_key="typed-output", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        input_payload="hello",
    )
    output = TypedOutput(
        day=date(2026, 9, 5),
        instant=datetime(2026, 9, 5, 12, 30, tzinfo=timezone.utc),
        amount=Decimal("123.45"),
        identifier=UUID("c06139d6-90bf-4bd7-979e-2d46604c9a41"),
        optional=None,
    )

    class Result:
        final_output = output
        raw_responses = [{"output": output}]
        last_response_id = "response-id"
        interruptions: list[Any] = []

        def release_agents(self) -> None:
            pass

    async def fake_run(*args: Any, **kwargs: Any) -> Result:
        return Result()

    monkeypatch.setattr("agentic_django.services.get_agent", lambda key: object())
    monkeypatch.setattr("agentic_django.services.Runner.run", fake_run)

    execute_run(str(run.id))

    run.refresh_from_db()
    expected = {
        "day": "2026-09-05",
        "instant": "2026-09-05T12:30:00Z",
        "amount": "123.45",
        "identifier": "c06139d6-90bf-4bd7-979e-2d46604c9a41",
        "optional": None,
    }
    assert run.status == AgentRun.Status.COMPLETED
    assert run.final_output == expected
    assert run.raw_responses == [{"output": expected}]
    assert run.error == ""
    assert TypedOutput.model_validate(run.final_output) == output
