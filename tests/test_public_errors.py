from __future__ import annotations

from typing import Any

import pytest
from django.test import Client, override_settings

from agentic_django.models import AgentRun, AgentSession
from agentic_django.services import execute_run


@pytest.mark.django_db()
@pytest.mark.parametrize("debug", [False, True])
def test_run_detail_exposes_exception_content_only_in_debug_mode(
    monkeypatch: pytest.MonkeyPatch, client: Client, user: Any, debug: bool,
) -> None:
    session = AgentSession.objects.create(session_key="errors", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hi"
    )
    private_text = "Authorization: Bearer private-test-token"

    def broken_agent(key: str) -> None:
        raise RuntimeError(private_text)

    monkeypatch.setattr("agentic_django.services.get_agent", broken_agent)
    client.force_login(user)
    with override_settings(DEBUG=debug):
        with pytest.raises(RuntimeError, match="private-test-token"):
            execute_run(str(run.id))
        response = client.get(f"/runs/{run.id}/")
    assert response.status_code == 200
    error = response.json()["error"]
    assert response.json()["status"] == AgentRun.Status.FAILED
    assert (private_text in error) is debug
    assert ("Traceback" in error) is debug
    if not debug:
        assert error == "The agent run failed. Contact support with the run ID."
