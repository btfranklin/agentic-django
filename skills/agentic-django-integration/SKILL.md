---
name: agentic-django-integration
description: Use when integrating agentic-django into a Django project, including settings, events, signals, views, and usage patterns.
---

# Agentic Django Integration

## Quick start (installed app)
1. Add `"agentic_django.apps.AgenticDjangoConfig"` to `INSTALLED_APPS`.
2. Include URLs: `path("agents/", include(("agentic_django.urls", "agents"), namespace="agents"))`.
3. Set required settings:
   - `AGENTIC_DJANGO_AGENT_REGISTRY`
   - `AGENTIC_DJANGO_DEFAULT_AGENT_KEY`
4. Run migrations: `python manage.py migrate`.

## References
- `references/quickstart.md`: end-to-end setup for a Django project.
- `references/registry.md`: building the agent registry callable.
- `references/htmx.md`: HTMX polling + fragment usage.
- `references/events.md`: event streaming endpoint + signal usage.
- `references/operations.md`: retention policy, cleanup commands, and recovery.

## Key invariants
- Settings prefix: `AGENTIC_DJANGO_*` only.
- Event streaming uses `Runner.run_streamed` (sync return) and consumes events via `RunResultStreaming.stream_events()`; `raw_response_event` is never stored.
- Events persist to `AgentEvent` and are exposed via `GET /runs/<uuid>/events/?after=<sequence>&limit=<n>`.
- After persistence, `agent_run_event` fires with `run`, `event`, `sequence`, `event_type`, `payload`.
- Sessions use `DatabaseSession` with ordered `AgentSessionItem` writes.
- Error storage is sanitized when `DEBUG=False`.

## Event usage
- Enable events: `AGENTIC_DJANGO_ENABLE_EVENTS = True`.
- Subscribe to `agent_run_event` for UI updates or notifications.
- Poll events: `GET /agents/runs/<uuid>/events/?after=<sequence>&limit=<n>`.

## Common integration steps
- Provide an agent registry callable that returns a dict of agent factories.
- Configure task backend via Django tasks (`TASKS`) if using background execution.
- Use the HTMX fragment endpoint for polling UI updates.
