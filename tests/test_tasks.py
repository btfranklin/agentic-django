from __future__ import annotations

import pytest

from agentic_django.tasks import run_agent_task


def test_run_agent_task_calls_execute_run(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, str] = {}

    def fake_execute(run_id: str) -> None:
        called["run_id"] = run_id

    monkeypatch.setattr("agentic_django.tasks.execute_run", fake_execute)
    run_agent_task.call("abc")
    assert called["run_id"] == "abc"
