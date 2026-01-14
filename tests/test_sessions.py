from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from django.test import override_settings

from agentic_django.models import AgentSessionItem
from agentic_django.sessions import DatabaseSession, get_session


@dataclass
class ExamplePayload:
    name: str
    count: int


@pytest.mark.django_db()
def test_database_session_lifecycle(user: Any) -> None:
    session = DatabaseSession.get_or_create("thread-1", user)
    assert session.session_id

    payloads = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    session._add_items(payloads)
    assert AgentSessionItem.objects.filter(session_id=session._session.id).count() == 2

    items = session._get_items(limit=None)
    assert items == payloads

    limited = session._get_items(limit=1)
    assert limited == payloads[-1:]

    popped = session._pop_item()
    assert popped == payloads[-1]

    session._clear_session()
    assert AgentSessionItem.objects.filter(session_id=session._session.id).count() == 0


@pytest.mark.django_db()
def test_database_session_serializes_items(user: Any) -> None:
    session = DatabaseSession.get_or_create("thread-serialize", user)
    items = [{"type": "message", "payload": ExamplePayload(name="hello", count=2)}]

    session._add_items(items)

    stored = AgentSessionItem.objects.get(session_id=session._session.id)
    assert stored.payload == {
        "type": "message",
        "payload": {"name": "hello", "count": 2},
    }
    assert session._get_items(limit=None) == [stored.payload]


@pytest.mark.django_db()
def test_get_session_uses_backend(user: Any) -> None:
    with override_settings(
        AGENTIC_DJANGO_SESSION_BACKEND="agentic_django.sessions.DatabaseSession"
    ):
        session = get_session("thread-2", user)
        assert isinstance(session, DatabaseSession)
