from __future__ import annotations

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from .models import AgentEvent, AgentRun, AgentSession, AgentSessionItem
from .services import enqueue_agent_run


def _owner_search_fields() -> list[str]:
    user_model = get_user_model()
    field_names = {field.name for field in user_model._meta.fields}
    lookups = []
    for name in dict.fromkeys([
        user_model.USERNAME_FIELD, user_model.get_email_field_name(),
    ]):
        if name not in field_names:
            continue
        field = user_model._meta.get_field(name)
        lookup = f"owner__{name}"
        while field.is_relation:
            field = field.target_field
            lookup += f"__{field.name}"
        lookups.append(lookup)
    return lookups


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
    search_fields = ("session_key",)
    inlines = [AgentSessionItemInline]

    def get_search_fields(self, request: HttpRequest) -> list[str]:
        return [*self.search_fields, *_owner_search_fields()]

    def get_readonly_fields(
        self, request: HttpRequest, obj: AgentSession | None = None,
    ) -> list[str]:
        if obj is not None:
            return ["owner", "session_key"]
        return []


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "agent_key", "owner", "status", "created_at")
    list_filter = ("status", "agent_key")
    search_fields = ("id", "agent_key")
    readonly_fields = ("created_at", "updated_at", "started_at", "finished_at")
    inlines = [AgentEventInline]
    actions = ["requeue_runs", "purge_runs"]

    def get_search_fields(self, request: HttpRequest) -> list[str]:
        return [*self.search_fields, *_owner_search_fields()]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: AgentRun | None = None,
    ) -> bool:
        return obj is None and super().has_change_permission(request, obj)

    def get_readonly_fields(
        self, request: HttpRequest, obj: AgentRun | None = None,
    ) -> list[str]:
        if obj is not None:
            return [field.name for field in self.model._meta.concrete_fields]
        return list(self.readonly_fields)

    @admin.action(permissions=["change"], description="Requeue selected runs")
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

    @admin.action(permissions=["delete"], description="Purge selected runs")
    def purge_runs(self, request: HttpRequest, queryset: QuerySet[AgentRun]) -> None:
        total = queryset.count()
        queryset.delete()
        self.message_user(request, f"Purged {total} runs.")


@admin.register(AgentEvent)
class AgentEventAdmin(admin.ModelAdmin):
    list_display = ("run", "event_type", "sequence", "created_at")
    list_filter = ("event_type",)
    search_fields = ("run__id",)
