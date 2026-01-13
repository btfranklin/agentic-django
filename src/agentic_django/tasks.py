from __future__ import annotations

from django_tasks import task

from agentic_django.services import execute_run


@task
def run_agent_task(run_id: str) -> None:
    execute_run(run_id)
