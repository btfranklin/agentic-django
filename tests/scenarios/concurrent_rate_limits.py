from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import django


def main() -> None:
    os.environ["DJANGO_SETTINGS_MODULE"] = "tests.settings"
    from django.conf import settings

    settings.DATABASES["default"]["NAME"] = sys.argv[1]

    django.setup()

    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import connections
    from django.utils import timezone
    from agentic_django.models import AgentRequestLimit
    from agentic_django.rate_limits import admit_request

    call_command("migrate", verbosity=0)
    user = get_user_model().objects.create_user(username="concurrent")
    max_calls = int(sys.argv[2])
    workers = 8

    def run_wave() -> None:
        barrier = Barrier(workers)

        def attempt(_: int) -> bool:
            barrier.wait(timeout=10)
            try:
                return admit_request(user, max_calls, 60)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            accepted = sum(executor.map(attempt, range(workers)))
        assert accepted == max_calls, accepted
        assert AgentRequestLimit.objects.get(owner=user).count == max_calls

    run_wave()
    AgentRequestLimit.objects.update(
        window_started_at=timezone.now() - timedelta(seconds=61),
    )
    run_wave()


if __name__ == "__main__":
    main()
