from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import override_settings

from agentic_django.models import AgentSessionItem
from agentic_django.sessions import DatabaseSession, get_session
from agentic_django.types import JsonObject, input_items


@pytest.mark.django_db()
def test_database_session_lifecycle(user: User) -> None:
    session = DatabaseSession.get_or_create("thread-1", user)
    assert session.session_id

    payloads = input_items([
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ])
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
def test_database_session_serializes_items(user: User) -> None:
    session = DatabaseSession.get_or_create("thread-serialize", user)
    items = input_items([{"role": "user", "content": "hello"}])

    session._add_items(items)

    stored = AgentSessionItem.objects.get(session_id=session._session.id)
    assert stored.payload == {"role": "user", "content": "hello"}
    assert session._get_items(limit=None) == [stored.payload]


@pytest.mark.django_db()
def test_get_session_uses_backend(user: User) -> None:
    with override_settings(
        AGENTIC_DJANGO_SESSION_BACKEND="agentic_django.sessions.DatabaseSession"
    ):
        session = get_session("thread-2", user)
        assert isinstance(session, DatabaseSession)


@pytest.mark.django_db()
def test_database_session_preserves_reasoning_summaries(user: User) -> None:
    session = DatabaseSession.get_or_create("reasoning", user)
    payload: JsonObject = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "Keep this summary."}],
    }
    session._add_items(input_items([payload]))

    stored = AgentSessionItem.objects.get(session_id=session._session.id)
    assert stored.payload == payload
    assert session._get_items(limit=None) == [payload]
    assert session._get_items(limit=None) == [payload]
    assert session._pop_item() == payload
