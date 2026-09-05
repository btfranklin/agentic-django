from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import async_to_sync
from agents.stream_events import AgentUpdatedStreamEvent
from agents import Agent

from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.serializers import StreamEventSerializer
from agentic_django.services import _consume_stream_events
from agentic_django.signals import agent_run_event


@pytest.mark.django_db(transaction=True)
def test_events_are_visible_before_stream_failure_and_signals_can_read_database(
    user: Any,
) -> None:
    session = AgentSession.objects.create(session_key="events", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )
    notifications = []

    def receiver(sender: Any, event: AgentEvent, **kwargs: Any) -> None:
        notifications.append(AgentEvent.objects.get(id=event.id).sequence)

    class Stream:
        async def stream_events(self) -> Any:
            yield AgentUpdatedStreamEvent(new_agent=Agent(name="first"))
            assert notifications == [1]
            yield AgentUpdatedStreamEvent(new_agent=Agent(name="second"))
            assert notifications == [1, 2]
            raise RuntimeError("stream interrupted")

    agent_run_event.connect(receiver, weak=False)
    try:
        with pytest.raises(RuntimeError, match="stream interrupted"):
            async_to_sync(_consume_stream_events)(
                run=run, result=Stream(), event_serializer=StreamEventSerializer(),
                starting_sequence=1,
            )
    finally:
        agent_run_event.disconnect(receiver)
    assert list(run.events.values_list("sequence", flat=True)) == [1, 2]
