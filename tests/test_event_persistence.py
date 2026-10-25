from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from agents import Agent
from agents.stream_events import AgentUpdatedStreamEvent, StreamEvent
from asgiref.sync import async_to_sync
from django.contrib.auth.models import User

from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.serializers import StreamEventSerializer
from agentic_django.services import _consume_stream_events
from agentic_django.signals import agent_run_event


@pytest.mark.django_db(transaction=True)
def test_events_are_visible_before_stream_failure_and_signals_can_read_database(
    user: User,
) -> None:
    session = AgentSession.objects.create(session_key="events", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )
    notifications = []

    def receiver(sender: object, event: AgentEvent, **kwargs: object) -> None:
        notifications.append(AgentEvent.objects.get(id=event.id).sequence)

    class Stream:
        @property
        def run_loop_task(self) -> asyncio.Task[None] | None:
            return None

        def cancel(self) -> None:
            pass

        def release_agents(self) -> None:
            pass

        async def stream_events(self) -> AsyncIterator[StreamEvent]:
            yield AgentUpdatedStreamEvent(new_agent=Agent[object](name="first"))
            assert notifications == [1]
            yield AgentUpdatedStreamEvent(new_agent=Agent[object](name="second"))
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


@pytest.mark.django_db(transaction=True)
def test_event_storage_failure_stops_stream_before_returning(
    user: User, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AgentSession.objects.create(session_key="cancel-stream", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )

    class Stream:
        cancelled = False
        cleaned_up = False
        closed = False
        released = False
        task: asyncio.Task[None] | None = None

        @property
        def run_loop_task(self) -> asyncio.Task[None] | None:
            return self.task

        async def work(self) -> None:
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                self.cleaned_up = True

        async def stream_events(self) -> AsyncIterator[StreamEvent]:
            self.task = asyncio.create_task(self.work())
            await asyncio.sleep(0)
            try:
                yield AgentUpdatedStreamEvent(new_agent=Agent[object](name="first"))
                await self.task
            finally:
                try:
                    await self.task
                except asyncio.CancelledError:
                    pass
                self.closed = True

        def cancel(self) -> None:
            self.cancelled = True
            assert self.task is not None
            self.task.cancel()

        def release_agents(self) -> None:
            self.released = True

    def broken_storage(*args: object) -> None:
        raise OSError("event storage unavailable")

    monkeypatch.setattr("agentic_django.services._persist_event", broken_storage)

    async def consume() -> None:
        stream = Stream()
        with pytest.raises(OSError, match="event storage unavailable"):
            await _consume_stream_events(
                run=run, result=stream, event_serializer=StreamEventSerializer(),
                starting_sequence=1,
            )
        assert stream.cancelled
        assert stream.cleaned_up
        assert stream.closed
        assert stream.released

    async_to_sync(consume)()
