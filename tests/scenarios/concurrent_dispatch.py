from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import django


def main() -> None:
    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
    from django.conf import settings

    settings.DATABASES["default"]["NAME"] = sys.argv[1]
    settings.AGENTIC_DJANGO_CONCURRENCY_LIMIT = 2

    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connections
    from agentic_django.models import AgentRun, AgentRunLock, AgentSession
    from agentic_django.services import _reserve_run_slot

    call_command("migrate", verbosity=0)
    owner = get_user_model().objects.create_user(username="concurrent")
    shared = bool(int(sys.argv[2]))
    if bool(int(sys.argv[3])):
        AgentRunLock.objects.create(key="global")
    session = AgentSession.objects.create(owner=owner, session_key="shared")
    runs = [
        AgentRun.objects.create(
            owner=owner, agent_key="default", input_payload="hello",
            session=session if shared else AgentSession.objects.create(
                owner=owner, session_key=str(i)
            ),
        )
        for i in range(8)
    ]
    barrier = Barrier(len(runs))

    def reserve(run: AgentRun) -> bool:
        barrier.wait(timeout=10)
        try:
            return _reserve_run_slot(run)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(runs)) as executor:
        accepted = sum(executor.map(reserve, runs))
    expected = 1 if shared else 2
    assert accepted == expected, accepted
    assert AgentRun.objects.filter(status="running").count() == expected
    assert AgentRun.objects.filter(status="pending").count() == 8 - expected


if __name__ == "__main__":
    main()
