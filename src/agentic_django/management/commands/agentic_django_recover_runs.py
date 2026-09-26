from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from agentic_django.services import recover_stuck_runs


class Command(BaseCommand):
    help = "Mark running agent runs as failed or requeue them."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--mode",
            choices=["fail", "requeue"],
            default="fail",
            help="Recovery mode for running runs.",
        )

        parser.add_argument(
            "--include-pending",
            action="store_true",
            help=(
                "Also recover pending runs with queue reservations. Stop workers "
                "and submissions, and remove their old queued tasks first."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        mode = options["mode"]
        updated = recover_stuck_runs(mode, include_pending=options["include_pending"])
        self.stdout.write(f"Recovered {updated} runs ({mode}).")
