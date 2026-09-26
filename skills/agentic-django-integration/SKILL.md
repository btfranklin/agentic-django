---
name: agentic-django-integration
description: Use when integrating agentic-django into a Django project, including settings, events, signals, views, and usage patterns.
---

# Agentic Django Integration

## Quick start (installed app)
Requires Python 3.12+ and Django 6.1 or later. The current target is Django 6.x.

1. Add `"agentic_django.apps.AgenticDjangoConfig"` to `INSTALLED_APPS`.
2. Include URLs: `path("agents/", include("agentic_django.urls", namespace="agents"))`.
3. Set `AGENTIC_DJANGO_AGENT_REGISTRY`. Set `AGENTIC_DJANGO_DEFAULT_AGENT_KEY`
   if the registry uses a default key other than `"default"`.
4. Run migrations: `python manage.py migrate`.

## References
- `references/quickstart.md`: end-to-end setup for a Django project.
- `references/registry.md`: building the agent registry callable.
- `references/htmx.md`: HTMX polling + fragment usage.
- `references/events.md`: event streaming endpoint + signal usage.
- `references/operations.md`: retention policy, cleanup commands, and recovery.
- `references/architecture.md`: run lifecycle, task dispatch, and concurrency notes.
- `references/data-model.md`: models, session storage, and serialization invariants.
- `references/errors-security.md`: error handling, ownership, and safety guidance.

## Key invariants
- Settings prefix: `AGENTIC_DJANGO_*` only.
- Event streaming uses `Runner.run_streamed` (sync return) and consumes events via `RunResultStreaming.stream_events()`; the default event serializer skips raw response events.
- Events persist to `AgentEvent` and are exposed via `GET /agents/runs/<uuid>/events/?after=<sequence>&limit=<n>`.
- After persistence, `agent_run_event` fires with `run`, `event`, `sequence`, `event_type`, `payload`.
- The default session backend uses `DatabaseSession` with ordered `AgentSessionItem` writes.
- Error storage is sanitized when `DEBUG=False`.

## Event usage
- Enable events: `AGENTIC_DJANGO_ENABLE_EVENTS = True`.
- Subscribe to `agent_run_event` for UI updates or notifications.
- Poll events: `GET /agents/runs/<uuid>/events/?after=<sequence>&limit=<n>`.

## Common integration steps
- Provide an agent registry callable that returns a dict of agent factories.
- Configure task backend via Django tasks (`TASKS`) if using background execution.
- Use `submit_agent_run` for custom submission after authentication and validation.
- Use the HTMX fragment endpoint for polling UI updates.
- Use manual recovery for stopped workers; `--include-pending` covers abandoned
  queue reservations after old tasks have been removed.
