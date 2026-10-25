from __future__ import annotations

from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError

from agentic_django.services import recover_stuck_runs


class Command(BaseCommand):
    help = "Mark running agent runs as failed or requeue them."

    def add_arguments(self, parser: ArgumentParser) -> None:
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

    def handle(self, *args: object, **options: object) -> None:
        mode = options["mode"]
        include_pending = options["include_pending"]
        if mode not in ("fail", "requeue") or not isinstance(mode, str):
            raise CommandError("mode must be fail or requeue")
        if not isinstance(include_pending, bool):
            raise CommandError("include_pending must be a boolean")
        updated = recover_stuck_runs(mode, include_pending=include_pending)
        self.stdout.write(f"Recovered {updated} runs ({mode}).")
