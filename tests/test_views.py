from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.test import override_settings
from django_htmx.http import HTMX_STOP_POLLING

from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.views import RUN_UPDATE_TRIGGER
from tests.support import RecordingSession


def _trigger_events(response: Any) -> dict[str, dict[str, Any]]:
    return json.loads(response["HX-Trigger"])


@pytest.mark.django_db()
def test_create_run_requires_session_key(client: Client, user: Any) -> None:
    client.force_login(user)
    response = client.post("/runs/", {"input": "hello"})
    assert response.status_code == 400


@pytest.mark.django_db()
def test_create_run_requires_input(client: Client, user: Any) -> None:
    client.force_login(user)
    response = client.post("/runs/", {"session_key": "thread"})
    assert response.status_code == 400


@pytest.mark.django_db()
def test_create_run_rejects_invalid_json(client: Client, user: Any) -> None:
    client.force_login(user)
    response = client.post(
        "/runs/",
        data="{",
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db()
def test_create_run_rejects_non_object_json(client: Client, user: Any) -> None:
    client.force_login(user)
    response = client.post(
        "/runs/",
        data=json.dumps(["not", "a", "dict"]),
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db()
def test_create_run_json_success(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    user: Any,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.get_agent_registry",
        lambda: {"default": lambda: object()},
    )
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run",
        lambda run_id: None,
    )

    payload = {"session_key": "thread", "input": "hello"}
    response = client.post(
        "/runs/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == AgentRun.Status.PENDING
    assert AgentRun.objects.filter(id=data["run_id"]).exists()


@pytest.mark.django_db()
def test_create_run_uses_session_backend(
    monkeypatch: pytest.MonkeyPatch, client: Client, user: Any
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.get_agent_registry",
        lambda: {"default": lambda: object()},
    )
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run",
        lambda run_id: None,
    )
    RecordingSession.called = False

    payload = {"session_key": "thread", "input": "hello"}
    with override_settings(
        AGENTIC_DJANGO_SESSION_BACKEND="tests.support.RecordingSession"
    ):
        response = client.post(
            "/runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert response.status_code == 200
    assert RecordingSession.called is True


@pytest.mark.django_db()
def test_create_run_htmx(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    user: Any,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.get_agent_registry",
        lambda: {"default": lambda: object()},
    )
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run",
        lambda run_id: None,
    )

    payload = {"session_key": "thread", "input": "hello"}
    response = client.post(
        "/runs/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert _trigger_events(response) == {RUN_UPDATE_TRIGGER: {}}
    assert b"run-container-" in response.content


@pytest.mark.django_db()
def test_create_run_unknown_agent(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    user: Any,
) -> None:
    client.force_login(user)
    monkeypatch.setattr("agentic_django.views.get_agent_registry", lambda: {})

    payload = {"session_key": "thread", "input": "hello", "agent_key": "missing"}
    response = client.post(
        "/runs/",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 400


@pytest.mark.django_db()
def test_create_run_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
    client: Client,
    user: Any,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.get_agent_registry",
        lambda: {"default": lambda: object()},
    )
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run",
        lambda run_id: None,
    )

    payload = {"session_key": "thread", "input": "hello"}
    with override_settings(AGENTIC_DJANGO_RATE_LIMIT="1/m"):
        first = client.post(
            "/runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        second = client.post(
            "/runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.django_db()
def test_create_run_payload_too_large(client: Client, user: Any) -> None:
    client.force_login(user)
    payload = {"session_key": "thread", "input": "x" * 50}
    with override_settings(AGENTIC_DJANGO_MAX_INPUT_BYTES=10):
        response = client.post(
            "/runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert response.status_code == 413


@pytest.mark.django_db()
def test_create_run_too_many_items(client: Client, user: Any) -> None:
    client.force_login(user)
    payload = {
        "session_key": "thread",
        "input": [{"role": "user", "content": "hi"}] * 3,
    }
    with override_settings(AGENTIC_DJANGO_MAX_INPUT_ITEMS=2):
        response = client.post(
            "/runs/",
            data=json.dumps(payload),
            content_type="application/json",
        )
    assert response.status_code == 413


@pytest.mark.django_db()
def test_run_detail_view(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.COMPLETED,
        input_payload="hello",
        final_output={"ok": True},
    )
    response = client.get(f"/runs/{run.id}/")
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(run.id)
    assert data["final_output"] == {"ok": True}


@pytest.mark.django_db()
def test_run_fragment_view(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
    )
    response = client.get(f"/runs/{run.id}/fragment/")
    assert response.status_code == 200
    assert _trigger_events(response) == {RUN_UPDATE_TRIGGER: {}}
    assert b"agent-run__status" in response.content


@pytest.mark.django_db()
def test_run_fragment_pending_includes_polling_attrs(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.PENDING,
        input_payload="hello",
    )

    response = client.get(f"/runs/{run.id}/fragment/")

    assert response.status_code == 200
    assert b"hx-get=" in response.content
    assert b"hx-trigger=" in response.content
    assert b"hx-on::afterSwap=" not in response.content


@pytest.mark.django_db()
def test_run_fragment_completed_removes_polling_attrs(
    client: Client,
    user: Any,
) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.COMPLETED,
        input_payload="hello",
    )

    response = client.get(f"/runs/{run.id}/fragment/", HTTP_HX_REQUEST="true")

    assert response.status_code == HTMX_STOP_POLLING
    assert b"hx-get=" not in response.content
    assert b"hx-trigger=" not in response.content
    assert b"hx-on::afterSwap=" not in response.content
    assert b"Completed" in response.content


@pytest.mark.django_db()
def test_run_fragment_completed_non_htmx_returns_200(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.COMPLETED,
        input_payload="hello",
    )

    response = client.get(f"/runs/{run.id}/fragment/")

    assert response.status_code == 200
    assert b"Completed" in response.content


@pytest.mark.django_db()
def test_session_items_view(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    session.items.create(sequence=1, payload={"role": "user", "content": "hello"})
    session.items.create(sequence=2, payload={"role": "assistant", "content": "hi"})

    response = client.get("/sessions/thread/items/?limit=1")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == [{"role": "assistant", "content": "hi"}]


@pytest.mark.django_db()
def test_session_items_view_htmx(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    session.items.create(sequence=1, payload={"role": "user", "content": "hello"})

    response = client.get("/sessions/thread/items/?limit=1", HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert b"agent-conversation__item" in response.content


@pytest.mark.django_db()
def test_run_events_view(client: Client, user: Any) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session,
        owner=user,
        agent_key="default",
        status=AgentRun.Status.RUNNING,
        input_payload="hello",
    )
    AgentEvent.objects.create(
        run=run,
        sequence=1,
        event_type="message_output_created",
        payload={"type": "run_item_stream_event", "name": "message_output_created"},
    )
    AgentEvent.objects.create(
        run=run,
        sequence=2,
        event_type="tool_called",
        payload={"type": "run_item_stream_event", "name": "tool_called"},
    )

    with override_settings(AGENTIC_DJANGO_ENABLE_EVENTS=True):
        response = client.get(f"/runs/{run.id}/events/?after=1")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(run.id)
    assert data["events"][0]["sequence"] == 2


@pytest.mark.django_db()
@pytest.mark.parametrize("text", ["123", "true", "null", '"quoted"', '["text"]'])
@pytest.mark.parametrize("as_json", [False, True])
def test_create_run_preserves_input_text(
    monkeypatch: pytest.MonkeyPatch, client: Client, user: Any,
    text: str, as_json: bool,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run", lambda run_id: None,
    )
    payload = {"session_key": "thread", "input": text}
    if as_json:
        response = client.post(
            "/runs/", data=json.dumps(payload), content_type="application/json",
        )
    else:
        response = client.post("/runs/", data=payload)
    assert response.status_code == 200
    assert AgentRun.objects.get(id=response.json()["run_id"]).input_payload == text


@pytest.mark.django_db()
def test_create_run_preserves_json_context_text(
    monkeypatch: pytest.MonkeyPatch, client: Client, user: Any,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run", lambda run_id: None,
    )
    payload = {"session_key": "thread", "input": "hello", "context": "123"}
    response = client.post(
        "/runs/", data=json.dumps(payload), content_type="application/json",
    )
    assert response.status_code == 200
    run = AgentRun.objects.get(id=response.json()["run_id"])
    assert run.metadata["context"] == "123"


@pytest.mark.django_db()
@pytest.mark.parametrize(
    "session_key", ["thread key", "thread/key", "café", "x" * 256, 123, ["thread"]],
)
def test_create_run_rejects_session_keys_outside_url_contract(
    client: Client, user: Any, session_key: Any,
) -> None:
    client.force_login(user)
    response = client.post(
        "/runs/", data=json.dumps({"session_key": session_key, "input": "hello"}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert not AgentSession.objects.exists()
    assert not AgentRun.objects.exists()


@pytest.mark.django_db()
@pytest.mark.parametrize("session_key", ["thread_A-123", "x" * 255])
def test_created_session_key_can_retrieve_history(
    monkeypatch: pytest.MonkeyPatch, client: Client, user: Any, session_key: str,
) -> None:
    client.force_login(user)
    monkeypatch.setattr(
        "agentic_django.views.enqueue_agent_run", lambda run_id: None,
    )
    response = client.post(
        "/runs/", data={"session_key": session_key, "input": "hello"},
    )
    assert response.status_code == 200
    response = client.get(f"/sessions/{session_key}/items/")
    assert response.status_code == 200
    assert response.json() == {"session_key": session_key, "items": []}


@pytest.mark.django_db()
@pytest.mark.parametrize("limit", ["-1", "invalid"])
@pytest.mark.parametrize("endpoint", ["items", "events"])
def test_history_endpoints_reject_invalid_limits(
    client: Client, user: Any, limit: str, endpoint: str,
) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    url = (
        "/sessions/thread/items/" if endpoint == "items" else f"/runs/{run.id}/events/"
    )
    with override_settings(AGENTIC_DJANGO_ENABLE_EVENTS=True):
        response = client.get(url, {"limit": limit})
    assert response.status_code == 400
    assert response.json()["error"] == "limit must be a non-negative integer"


@pytest.mark.django_db()
@pytest.mark.parametrize("endpoint", ["items", "events"])
def test_history_endpoints_accept_zero_limit(
    client: Client, user: Any, endpoint: str,
) -> None:
    client.force_login(user)
    session = AgentSession.objects.create(session_key="thread", owner=user)
    session.items.create(sequence=1, payload={"role": "user", "content": "hello"})
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    AgentEvent.objects.create(
        run=run, sequence=1, event_type="tool_called", payload={"name": "tool"},
    )
    url = (
        "/sessions/thread/items/" if endpoint == "items" else f"/runs/{run.id}/events/"
    )
    with override_settings(AGENTIC_DJANGO_ENABLE_EVENTS=True):
        response = client.get(url, {"limit": 0})
    assert response.status_code == 200
    assert response.json()[endpoint] == []


@pytest.mark.django_db()
@pytest.mark.parametrize("agent_key", [["default"], [], {"key": "default"}, 123])
def test_create_run_rejects_invalid_agent_key_type(
    client: Client, user: Any, agent_key: Any,
) -> None:
    client.force_login(user)
    response = client.post(
        "/runs/", content_type="application/json",
        data=json.dumps({
            "session_key": "thread", "input": "hello", "agent_key": agent_key,
        }),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "agent_key must be a string"
    assert not AgentRun.objects.exists()


@pytest.mark.django_db()
@pytest.mark.parametrize('authenticated', [False, True])
def test_endpoints_deny_access_to_other_owners(
    client: Client, user: Any, authenticated: bool,
) -> None:
    from django.contrib.auth import get_user_model

    owner = get_user_model().objects.create_user(username='private-owner')
    session = AgentSession.objects.create(owner=owner, session_key='private')
    session.items.create(sequence=1, payload={'content': 'private history'})
    run = AgentRun.objects.create(
        owner=owner, session=session, agent_key='default', input_payload='private',
    )
    AgentEvent.objects.create(run=run, sequence=1, event_type='message', payload={})
    if authenticated:
        client.force_login(user)
    with override_settings(AGENTIC_DJANGO_ENABLE_EVENTS=True):
        for url in (
            f'/runs/{run.pk}/', f'/runs/{run.pk}/fragment/',
            f'/runs/{run.pk}/events/', '/sessions/private/items/',
        ):
            response = client.get(url)
            assert response.status_code == (404 if authenticated else 302)


@pytest.mark.django_db()
def test_anonymous_client_cannot_create_run(client: Client) -> None:
    response = client.post('/runs/', {'session_key': 'private', 'input': 'hi'})
    assert response.status_code == 302
    assert not AgentRun.objects.exists()
    assert not AgentSession.objects.exists()


@pytest.mark.django_db()
def test_run_creation_requires_csrf_token(user: Any) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post('/runs/', {'session_key': 'private', 'input': 'hi'})
    assert response.status_code == 403
    assert not AgentRun.objects.exists()
