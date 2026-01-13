from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet
from django.utils import timezone

from agentic_django.conf import get_settings, normalize_cleanup_policy
from agentic_django.models import AgentEvent, AgentRun, AgentSession

DEFAULT_BATCH_SIZE = 500
DEFAULT_RUN_STATUSES = [AgentRun.Status.COMPLETED, AgentRun.Status.FAILED]


class Command(BaseCommand):
    help = "Prune old Agentic Django data (runs, events, sessions)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--events-days", type=int)
        parser.add_argument("--runs-days", type=int)
        parser.add_argument("--sessions-days", type=int)
        parser.add_argument("--runs-statuses", type=str)
        parser.add_argument("--batch-size", type=int)
        parser.add_argument("--dry-run", action="store_true", default=False)
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--sessions-require-empty",
            action="store_true",
            dest="sessions_require_empty",
        )
        group.add_argument(
            "--sessions-allow-nonempty",
            action="store_false",
            dest="sessions_require_empty",
        )
        parser.set_defaults(sessions_require_empty=None)

    def handle(self, *args: Any, **options: Any) -> None:
        policy = normalize_cleanup_policy(get_settings().cleanup_policy)
        policy = self._apply_overrides(policy, options)

        if not any(
            key in policy
            for key in ("events_days", "runs_days", "sessions_days")
        ):
            self.stdout.write("No cleanup policy configured; nothing to do.")
            return

        batch_size = policy.get("batch_size", DEFAULT_BATCH_SIZE)
        if batch_size < 1:
            raise CommandError("batch_size must be >= 1")

        dry_run = bool(options.get("dry_run"))
        prefix = "Would delete" if dry_run else "Deleted"

        now = timezone.now()

        if "events_days" in policy:
            cutoff = now - timedelta(days=policy["events_days"])
            count = self._delete_queryset(
                AgentEvent.objects.filter(created_at__lt=cutoff),
                batch_size,
                dry_run,
            )
            self.stdout.write(f"{prefix} {count} events.")

        if "runs_days" in policy:
            cutoff = now - timedelta(days=policy["runs_days"])
            statuses = policy.get("runs_statuses", DEFAULT_RUN_STATUSES)
            count = self._delete_queryset(
                AgentRun.objects.filter(status__in=statuses, updated_at__lt=cutoff),
                batch_size,
                dry_run,
            )
            self.stdout.write(f"{prefix} {count} runs.")

        if "sessions_days" in policy:
            cutoff = now - timedelta(days=policy["sessions_days"])
            sessions = AgentSession.objects.filter(updated_at__lt=cutoff)
            require_empty = policy.get("sessions_require_empty", True)
            if require_empty:
                sessions = (
                    sessions.filter(runs__isnull=True, items__isnull=True)
                    .distinct()
                )
            count = self._delete_queryset(sessions, batch_size, dry_run)
            self.stdout.write(f"{prefix} {count} sessions.")

    def _apply_overrides(self, policy: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        updated = dict(policy)

        for key, option_key in (
            ("events_days", "events_days"),
            ("runs_days", "runs_days"),
            ("sessions_days", "sessions_days"),
            ("batch_size", "batch_size"),
        ):
            value = options.get(option_key)
            if value is None:
                continue
            if value < 1:
                raise CommandError(f"{option_key} must be >= 1")
            updated[key] = value

        if options.get("runs_statuses"):
            updated["runs_statuses"] = self._parse_statuses(options["runs_statuses"])

        if options.get("sessions_require_empty") is not None:
            updated["sessions_require_empty"] = options["sessions_require_empty"]

        return updated

    def _parse_statuses(self, value: str) -> list[str]:
        statuses = [status.strip() for status in value.split(",") if status.strip()]
        if not statuses:
            raise CommandError("runs-statuses cannot be empty")
        valid = {choice for choice, _ in AgentRun.Status.choices}
        invalid = sorted(set(statuses) - valid)
        if invalid:
            raise CommandError(f"Invalid run status values: {', '.join(invalid)}")
        return statuses

    def _delete_queryset(
        self,
        queryset: QuerySet[Any],
        batch_size: int,
        dry_run: bool,
    ) -> int:
        if dry_run:
            return queryset.count()
        total = 0
        base = queryset.order_by("pk")
        while True:
            ids = list(base.values_list("pk", flat=True)[:batch_size])
            if not ids:
                break
            base.model.objects.filter(pk__in=ids).delete()
            total += len(ids)
        return total
