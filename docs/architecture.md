# Architecture

Agentic Django is a reusable Django 6 app that persists OpenAI Agents SDK
sessions, dispatches agent runs through Django tasks, and exposes owner-scoped
JSON and HTMX polling endpoints.

## Package Surface

| Area | Files | Responsibility |
| --- | --- | --- |
| App config | `src/agentic_django/apps.py` | Registers the Django app and validates settings during app startup. |
| Settings | `src/agentic_django/conf.py` | Reads and validates `AGENTIC_DJANGO_*` settings, cleanup policy, rate limits, and concurrency limits. |
| Models | `src/agentic_django/models.py` | Stores sessions, ordered session items, runs, semantic events, and a global dispatch lock row. |
| Session backend | `src/agentic_django/sessions.py` | Implements the Agents SDK session protocol with ordered database-backed items. |
| Registry | `src/agentic_django/registry.py` | Loads the host app's agent factory registry and resolves `agent_key` values. |
| Serializers | `src/agentic_django/serializers.py` | Normalizes SDK results, session items, and semantic stream events into JSON-safe payloads. |
| Services | `src/agentic_django/services.py` | Enqueues runs, dispatches pending work, executes SDK runs, persists outputs/events, sends signals, and recovers stuck runs. |
| Tasks | `src/agentic_django/tasks.py` | Defines the Django task entry point that calls `execute_run`. |
| Views and URLs | `src/agentic_django/views.py`, `src/agentic_django/urls.py` | Provide authenticated run creation, status, fragment, event, and session-history endpoints. |
| Templates and CSS | `src/agentic_django/templates/agentic_django/`, `src/agentic_django/static/agentic_django/` | Ship default HTMX fragments and minimal package styling. |
| Operations | `src/agentic_django/management/commands/` | Provides cleanup and run-recovery commands. |

## Runtime Flow

1. `AgentRunCreateView` authenticates the user, validates payload shape and
   limits, resolves the agent key, ensures the configured session backend can
   create the session, creates an `AgentRun`, and enqueues it.
2. `enqueue_agent_run` schedules `run_agent_task` through the configured
   Django-tasks backend and stores a task id when one is available.
3. `execute_run` reserves a concurrency slot, sends `agent_run_started`, builds
   the agent/session/context/run options, and calls the Agents SDK runner.
4. If events are disabled, `Runner.run` is executed through `async_to_sync`.
   If events are enabled, `Runner.run_streamed` is used and semantic
   `RunItemStreamEvent`/`AgentUpdatedStreamEvent` payloads are persisted.
   Raw token events are intentionally skipped.
5. Completion stores `final_output`, `raw_responses`, `last_response_id`, clears
   the task id, marks the run completed, releases agents, and sends
   `agent_run_completed`.
6. Failure stores a sanitized error when `DEBUG=False`, marks the run failed,
   sends `agent_run_failed`, and re-raises for worker observability.
7. HTMX clients poll the fragment endpoint. Terminal runs return
   `HttpResponseStopPolling` and emit `HX-Trigger: run-update` so dependent UI
   panels can update from the same polling loop.

## Ownership And Security Invariants

- `AgentSession` and `AgentRun` have an `owner` foreign key.
- Request-facing views must filter by both identifier and `owner`.
- `AgentSession.session_key` is unique only within an owner.
- Event access is mediated through the owning run.
- Error text is traceback-level only when `DEBUG=True`; production errors are
  summarized.
- Rate limits and request-size/input-item limits are enforced before run
  creation when configured.
- Agent registries are host-app supplied. Do not expose powerful tools to
  untrusted input without host-app validation or allowlists.

## Dependency Direction

Keep dependencies mostly one-way:

- `models.py` should not import views, tasks, services, registry code, or
  serializers.
- `serializers.py` should stay framework-light and avoid importing models,
  services, tasks, or views.
- `sessions.py` may depend on settings, models, serializers, and signals.
- `services.py` owns orchestration and may depend on settings, models,
  registry, serializers, sessions, tasks, and signals.
- `tasks.py` should remain a thin task entry point into services.
- `views.py` owns HTTP payload validation and response shape, then delegates
  execution to services/session helpers.

If a change needs a new cross-layer edge, document the reason here and add a
test for the behavior that made the edge necessary.

## Extension Points

- `AGENTIC_DJANGO_AGENT_REGISTRY`: dotted path to a callable returning
  `dict[str, Callable[[], Agent]]`.
- `AGENTIC_DJANGO_SESSION_BACKEND`: backend with
  `get_or_create(session_key, owner)`.
- `AGENTIC_DJANGO_SESSION_ITEM_SERIALIZER`, `AGENTIC_DJANGO_SERIALIZER`, and
  `AGENTIC_DJANGO_EVENT_SERIALIZER`: JSON boundary customization.
- `AGENTIC_DJANGO_CONTEXT_FACTORY`: rebuilds typed context from run metadata.
- Django signals: `agent_session_created`, `agent_run_started`,
  `agent_run_completed`, `agent_run_failed`, and `agent_run_event`.
- Template overrides: downstream projects may override
  `templates/agentic_django/...` paths.

## Current Limits

- The package uses polling in v1; it does not ship SSE or WebSocket push.
- The default session backend is database-backed. Alternative backends must
  satisfy the Agents SDK session protocol and preserve owner scoping.
- Celery is not part of the package contract. Use Django tasks and configure an
  RQ-backed task backend when production-like background workers are needed.
- OpenAI server-managed conversations are not the core storage model; local
  sessions are the default for provider-agnostic reuse.
