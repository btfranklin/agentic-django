from __future__ import annotations

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from .models import AgentEvent, AgentRun, AgentSession, AgentSessionItem
from .services import enqueue_agent_run


class AgentSessionItemInline(admin.TabularInline):
    model = AgentSessionItem
    extra = 0
    readonly_fields = ("sequence", "payload", "created_at")


class AgentEventInline(admin.TabularInline):
    model = AgentEvent
    extra = 0
    readonly_fields = ("sequence", "event_type", "payload", "created_at")
    ordering = ("sequence",)


@admin.register(AgentSession)
class AgentSessionAdmin(admin.ModelAdmin):
    list_display = ("session_key", "owner", "created_at", "updated_at")
    search_fields = ("session_key", "owner__username", "owner__email")
    inlines = [AgentSessionItemInline]


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_key", "owner", "status", "created_at")
    list_filter = ("status", "agent_key")
    search_fields = ("id", "agent_key", "owner__username", "owner__email")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    inlines = [AgentEventInline]
    actions = ["requeue_runs", "purge_runs"]

    @admin.action(description="Requeue selected runs")
    def requeue_runs(self, request: HttpRequest, queryset: QuerySet[AgentRun]) -> None:
        runs = queryset.exclude(status=AgentRun.Status.RUNNING)
        run_ids = list(runs.values_list("id", flat=True))
        updated = runs.update(
            status=AgentRun.Status.PENDING,
            error="",
            final_output=None,
            raw_responses=None,
            last_response_id="",
            started_at=None,
            finished_at=None,
            task_id="",
            updated_at=timezone.now(),
        )
        for run_id in run_ids:
            enqueue_agent_run(str(run_id))
        skipped = queryset.filter(status=AgentRun.Status.RUNNING).count()
        self.message_user(
            request,
            f"Requeued {updated} runs. Skipped {skipped} running runs.",
        )

    @admin.action(description="Purge selected runs")
    def purge_runs(self, request: HttpRequest, queryset: QuerySet[AgentRun]) -> None:
        total = queryset.count()
        queryset.delete()
        self.message_user(request, f"Purged {total} runs.")


@admin.register(AgentEvent)
class AgentEventAdmin(admin.ModelAdmin):
    list_display = ("run", "event_type", "sequence", "created_at")
    list_filter = ("event_type",)
    search_fields = ("run__id",)
