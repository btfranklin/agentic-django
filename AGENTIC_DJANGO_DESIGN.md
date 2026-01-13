# Agentic Django Integration Design

## Overview

This document captures the goals, guiding principles, and detailed design for a reusable Django package that layers on top of the OpenAI Agents SDK. The package targets server environments such as Sevalla where the application runs under ASGI and should orchestrate long-lived agent runs without Celery-style infrastructure, leaning on Django 6’s built-in tasks framework where background execution is required.

The document is intended to be a hand-off reference for implementation. It enumerates the data model, asynchronous workflow, API surface, frontend integrations (particularly HTMX), and extension points required to deliver a production-ready experience.

## Goals

- **Drop-in Django app**: Ship as a reusable Django application (e.g., `agentic_django`) that installs via pip, provides migrations, URLs, and optional admin screens, similar to packages like `django-allauth`.
- **Async-first orchestration**: Use Django 6’s tasks framework to run agent work outside the request/response cycle (no Celery required), keeping request/response semantics simple (polling only) in v1.
- **Session persistence**: Mirror the Agents SDK `Session` protocol so conversation history, tool outputs, and metadata survive process restarts and can be shared across multiple web nodes.
- **Status visibility**: Expose run state (`pending`, `running`, `completed`, `failed`) along with final output so frontends can poll for updates.
- **HTMX-friendly interface**: Provide default HTML fragments and endpoints tailored to HTMX usage without splitting the package into multiple apps. The app should also remain REST-compatible for non-HTMX consumers.
- **Alignment with Agents SDK types**: Reuse SDK data structures (sessions, run results, streamed events) where feasible to minimize translation and keep parity with upstream features.
- **Extensibility**: Offer hooks for custom tooling, alternative persistence backends, and different notification strategies.

## Non-Goals

- Real-time push transport beyond Server-Sent Events (SSE). Implementers may add WebSocket support as an extension but it is not required for the initial release.
- Implementing the OpenAI webhook-based Responses API flow. The package assumes the existing SDK interface that keeps the request open (streaming) or runs work out-of-band (Django 6 tasks).
- Supporting OpenAI server-managed conversations (`conversation_id` / `previous_response_id`) in the core design. The default storage model is local Sessions for provider-agnostic reuse.
- Cross-language support. This package targets Django (Python) applications specifically.
- Server-push transport in the initial release. The v1 package uses polling only (no SSE/WebSockets).

## Architecture Overview

```
request (HTMX hx-post) ──> Submission view ──┐
                                            │ create AgentRun row
                                            │ enqueue background task
                                            ▼
                                  background worker process
                     (await Runner.run or Runner.run_streamed (sync))
                                            │
                                     update persistence
                                            │
                                            ▼
                                 HTMX poll (hx-get)
                                      renders fragments
```

Key components:

- **Models**: `AgentSession`, `AgentRun`, optional `AgentEvent`.
- **Session backend**: Implements `agents.memory.Session` using the database.
- **Services**: Utilities to launch runs and handle completion callbacks.
- **Views**: HTMX-friendly endpoints for submission and status, plus REST alternatives.
- **Templates**: HTML fragments representing run state.
- **Signals/Hooks**: Allow customization during run lifecycle events.
- **Settings**: Configure agent registry, session backend, serialization, and cleanup policies.

## Data Model Design

### AgentSession

Represents a logical conversation thread. Maps to the `Session` protocol (`src/agents/memory/session.py:10`). Fields:
- `id` (UUID primary key).
- `session_key`: Externally visible identifier (e.g., user-scoped slug or ID).
- `owner`: FK to `auth.User` for per-user ownership enforcement.
- `created_at`, `updated_at`.
- `metadata`: JSON field for arbitrary context (optional).

Methods:
- `get_items(limit=None)`: Returns stored conversation history as `TResponseInputItem` blobs.
- `add_items(items)`: Appends new items.
- `pop_item()`, `clear_session()`: Maintain compatibility with the protocol.

Implementation detail: store items in a related table (`AgentSessionItem`) with ordered entries containing serialized SDK input items. Add an explicit `sequence` integer for ordering and assign it under a `select_for_update()` transaction on the session row to avoid interleaved writes. Serialization should use JSON representation compatible with `ItemHelpers.tool_call_output_item` to avoid loss; the default session item serializer should normalize SDK objects into JSON-safe dicts.

### AgentRun

Represents a single invocation of `Runner.run`.

Fields:
- `id` (UUID).
- `session` (FK to `AgentSession`).
- `owner`: FK to `auth.User` for per-user ownership enforcement.
- `agent_key`: String key used to resolve an `Agent` instance from the registry/factory.
- `status` (`pending`, `running`, `completed`, `failed`).
- `input_payload`: Original user request string or structured JSON.
- `final_output`: JSON/BLOB storing the `RunResult.final_output`.
- `raw_responses`: Optional serialized list of `ModelResponse` objects.
- `last_response_id`: Cached `RunResult.last_response_id`.
- `error`: Text field for stack trace or user-friendly message on failure.
- `started_at`, `finished_at`.
- `metadata`: JSON for run-specific configuration (model name, user ID, etc.).
- `task_id`: Optional background task identifier for traceability/cancellation.

### AgentEvent (optional)

Stores streamed events or intermediate updates for richer UIs.

Fields:
- `run` (FK to `AgentRun`).
- `sequence`: Monotonic integer.
- `event_type`: Enum (message, tool_call, reasoning, guardrail, system).
- `payload`: JSON payload from `RunItemStreamEvent` (semantic items only).
- `created_at`.

Use when consumer wants a timeline while the run executes. For minimal installations, the table can be disabled via setting.
Serialization must be explicit: raw SDK event objects should be normalized into JSON-safe dicts before persistence. Raw response token events are intentionally not stored.

## Session Backend Abstraction

Expose a factory (`get_session(session_key: str, owner: User) -> Session`) configurable in settings. Default implementation uses `AgentSession` plus `AgentSessionItem`. Allow alternative backends:

- Database (default).
- Redis (`agents.memory.RedisSession` wrapped by adapter storing `session_id`).
- Custom class path from settings (`AGENTIC_DJANGO_SESSION_BACKEND = "..."`).

Ensure adapter returns objects fulfilling the async SDK `Session` protocol so existing agent code can pass them directly into `Runner.run`.
If you pass `session` to `Runner.run`, do not manually append `result.to_input_list()` afterward, since the SDK already writes history.

## Asynchronous Workflow

1. Submission view validates request, locates/creates `AgentSession`, creates an `AgentRun` row with `status="pending"` and `agent_key`.
2. Enqueue background execution using Django 6 tasks. Avoid `asyncio.create_task()` in request handlers as the primary production mechanism; it’s not durable across restarts and can behave unpredictably with multiple web workers.
3. Task updates row to `status="running"`, then executes the run using `Runner.run` (async; wrap with `async_to_sync`) or `Runner.run_streamed` (sync return; consume `RunResultStreaming.stream_events()` when events are enabled). This preserves a sync-first task DX.
4. Upon completion:
   - Persist final output and raw responses.
   - If `session` was passed to `Runner.run`, rely on SDK persistence rather than re-appending history.
   - Update `status="completed"` and `finished_at`.
   - Optionally fire Django signals (`agent_run_completed`) with result object.
5. On exception:
   - Update `status="failed"`, store error summary, re-raise to propagate to observability.
   - Fire `agent_run_failed` signal.

## API Surface

### URL Configuration

Include a urls module that can be mounted under `/agents/`:

- `POST /agents/runs/` → `AgentRunCreateView`: accepts HTMX or JSON submissions, returns fragment with spinner plus `run_id`.
- `GET /agents/runs/<uuid:run_id>/` → `AgentRunDetailView`: returns JSON summary (status, final_output).
- `GET /agents/runs/<uuid:run_id>/fragment/` → `AgentRunFragmentView`: HTMX partial.
- `GET /agents/runs/<uuid:run_id>/events/` → `AgentRunEventsView`: JSON list of stored events (when enabled).
- `GET /agents/sessions/<slug:session_key>/items/` → conversation history (optional, JSON or HTML).

### Submission Contract

Accept payload fields:
- `session_key`: identifies the conversation (scoped to the authenticated user).
- `input`: string or structured JSON representing user message. If you pass a list input while using session memory, require `RunConfig.session_input_callback`.
- Optional `agent_key`: selects which agent definition to use (default is configurable).
- Optional `config` object: maps to `RunConfig` and `RunOptions` (model override, max_turns).
- Optional `context`: JSON payload for a context factory to rebuild the typed context object.

Return:
- `run_id`.
- For HTMX, HTML fragment with `hx-get` or `hx-sse` instructions (see next section).

## HTMX Integration

Adapt the API to be friendly with HTMX progressive enhancement:

- **Submission Flow**: Form uses `hx-post="/agents/runs/" hx-target="#run-container" hx-swap="outerHTML"`. The response fragment includes the spinner, `run_id` in data attributes, and auto-triggered polling:

  ```html
  <div id="run-container" data-run-id="{{ run.id }}" hx-get="{% url 'agents:run-fragment' run.id %}"
       hx-trigger="load delay:2s, every 2s"
       hx-target="#run-container" hx-swap="outerHTML">
      {% include "agents/partials/run_pending.html" %}
  </div>
  ```

- **Status Fragments**: Template `agents/partials/run_status.html` renders based on `run.status` (`pending`, `running`, `completed`, `failed`). When `completed`, it displays formatted `final_output` using project-provided template tags.
- **Django 6 template partials (optional)**: Where it helps readability, use Django 6’s `{% partialdef %}` / `{% partial %}` to define and reuse fragments within a template, instead of proliferating small include files.

- **Template Tags**: Provide `{% agent_run_fragment run %}` and `{% agent_conversation session %}` tags to encapsulate markup.

- **Styling**: Ship basic Tailwind-less CSS classes for spinners and states, allowing host apps to override. Provide an optional stylesheet at `src/agentic_django/static/agentic_django/agentic_django.css`.

## Settings and Configuration

Expose primary settings with sensible defaults:

- `AGENTIC_DJANGO_AGENT_REGISTRY`: dotted path to callable returning a mapping of `agent_key -> Agent factory`.
- `AGENTIC_DJANGO_DEFAULT_AGENT_KEY`: default agent key if not supplied in input.
- `AGENTIC_DJANGO_SESSION_BACKEND`: dotted path to session backend class (default: database-backed `DatabaseSession`).
- `AGENTIC_DJANGO_SESSION_ITEM_SERIALIZER`: dotted path to serializer that normalizes session items to JSON-safe payloads.
- `AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS`: dict merged into every `Runner.run` call (e.g., `{"max_turns": 6}`).
- `AGENTIC_DJANGO_SERIALIZER`: handles (de)serialization of `final_output` and intermediate items (default JSON).
- `AGENTIC_DJANGO_ENABLE_EVENTS`: boolean to toggle `AgentEvent` creation.
- `AGENTIC_DJANGO_EVENT_SERIALIZER`: dotted path to serializer that normalizes stream events to JSON-safe payloads (default: `StreamEventSerializer`).
- `AGENTIC_DJANGO_CLEANUP_POLICY`: options for pruning old runs/events/sessions.
- `AGENTIC_DJANGO_CONCURRENCY_LIMIT`: maximum concurrent background tasks; default to an auto value based on available CPU count (overrideable). Enforce atomically with DB locking rather than a naive count.
- `AGENTIC_DJANGO_CONTEXT_FACTORY`: dotted path to callable that rebuilds a typed context object from request/run metadata.
- `AGENTIC_DJANGO_RATE_LIMIT`: per-user throttle for run creation (e.g., `20/m`).
- `AGENTIC_DJANGO_MAX_INPUT_BYTES`: hard cap on request body size for run creation.
- `AGENTIC_DJANGO_MAX_INPUT_ITEMS`: cap on list-style inputs to avoid abuse.
- `AGENTIC_DJANGO_STARTUP_RECOVERY`: how to handle `running` runs on startup (`ignore`, `fail`, `requeue`; default `requeue`).
- `TASKS`: Django tasks backend configuration; in production demos, use `django_tasks.backends.rq.RQBackend` with `django-rq`.

Settings should be documented and validated at startup.

## Hook & Signal System

Provide Django signals (or callback registry) to integrate custom logic:

- `agent_run_started(run)` fired after the run is enqueued/started.
- `agent_run_completed(run, result)` fired after success.
- `agent_run_failed(run, exception)` fired on failure.
- `agent_session_created(session)` fired when new session is created.
- `agent_run_event(run, event, sequence, event_type, payload)` fired after a run event is stored (when events are enabled).

Allow consumers to register pipeline hooks (middleware-like) for input preprocessing, output post-processing, or logging.

## Admin Interface

Register admin models for `AgentSession`, `AgentRun`, and `AgentEvent` (if enabled). Provide list filters for status, search by session key, inline display of recent events, and actions to retry or purge runs.

## Error Handling and Resilience

- Detect server restarts: on startup, mark any `running` runs as `failed` with `error="Server restart"` or trigger a requeue mechanism (executed lazily on first dispatch/execute to avoid DB work in `AppConfig.ready()`).
- Wrap `Runner.run` calls with try/except to capture `AgentsException`, `UserError`, and generic exceptions (`src/agents/exceptions.py`), storing a friendly message (full traceback only when `DEBUG=True`).
- Ensure long-running tasks honor Python’s cancellation semantics; respond to `asyncio.CancelledError` by marking runs as failed.
- Provide management commands to clean up aged runs/events and to recover stuck runs.
- Document the required worker process for Django 6 tasks, and provide a runbook snippet to start it in production.

## Retention and Operations

- Provide a cleanup policy (`AGENTIC_DJANGO_CLEANUP_POLICY`) that defines retention windows for runs, events, and sessions (`events_days`, `runs_days`, `runs_statuses`, `sessions_days`, `sessions_require_empty`, `batch_size`).
- Expose `agentic_django_cleanup` for pruning in batches with a `--dry-run` preview.
- Expose `agentic_django_recover_runs` for manual recovery or requeue during maintenance.

## Security Considerations

- Authenticate submission endpoint. Enforce per-user ownership on all session/run queries by filtering on `owner` and rejecting cross-user access.
- Enforce rate limiting and payload validation to guard against malicious inputs (size limits, allowed tool invocation).
- If you later add SSE endpoints or embed third-party scripts, consider enabling Django 6’s built-in Content Security Policy middleware and setting a CSP that permits the required `connect-src`/`script-src` while keeping defaults tight.
- If you later enable SSE, ensure event streams respect CSRF and session authentication. Support `Last-Event-ID` for replay and avoid leaking cross-user run IDs.
- Keep agent tool registries scoped; avoid exposing powerful tools to untrusted input without additional validation or allowlists.
- Sensitive data in `final_output` or event logs should be filtered or encrypted as needed (tie into Agents SDK tracing flags like `trace_include_sensitive_data`).

## Testing Strategy

- Unit tests for models, session backend behavior, and serializer round-trips.
- Async view tests verifying background task creation and status updates.
- Integration tests using `Runner.run` with a mock agent or stub model to simulate tool calls.
- Template tests confirming HTMX fragments render correctly for each status.
- Optional tests for event recording behavior if events are enabled.

## Implementation Roadmap

1. **Bootstrap app**: Create Django app skeleton with settings, migrations, admin.
2. **Data layer**: Implement `AgentSession`, `AgentSessionItem`, `AgentRun`, `AgentEvent`.
3. **Session backend**: Write database-backed `DatabaseSession` implementing `Session` protocol.
4. **Services**: Implement background task launcher and completion handlers.
5. **Views & URLs**: Add submission/detail/event endpoints (HTMX + JSON).
6. **Templates**: Ship default fragments and template tags.
7. **Signals**: Wire lifecycle events.
8. **Configuration**: Validate settings, document usage.
9. **Documentation**: Provide quickstart guide and integration examples (HTMX forms, polling).
10. **Testing & QA**: Cover asynchronous behavior, error cases, and admin UI.

## Future Enhancements

- **Webhook-based orchestration**: Integrate future Agents SDK features for OpenAI-driven webhooks when available.
- **Task durability**: Optional integration with persistent job queues (Django-Q, dramatiq) for environments that require guaranteed execution after crashes.
- **Command-line utilities**: Management commands to summarize or export runs.
- **Analytics**: Aggregate usage metrics per agent/session and expose in admin dashboards.

## Conclusion

The proposed Django package embraces the asynchronous design of the OpenAI Agents SDK, provides reusable building blocks to persist agent state, and offers a smooth developer experience—especially for HTMX-driven UIs. Implementing along these guidelines should enable teams to deploy sophisticated agent workflows on platforms like Sevalla without introducing extra worker infrastructure while preserving extensibility for future features.

## Resolved Decisions

- Keep HTMX and API endpoints in one package; no split into separate apps.
- Default to Django 6 tasks for background execution with an RQ-backed Django-tasks worker for production demos.
- Use local Sessions as the default conversation store; no OpenAI Conversations API integration in the core design.
- Default to sync task execution with an `async_to_sync` bridge for `Runner.run`.
- Enforce per-user ownership with `owner` FKs on `AgentSession` and `AgentRun`.
- No client-side push transport in the initial release (polling only).
- Store full run outputs by default (no truncation in v1).
- Concurrency limit defaults to an auto value based on CPU count and is enforced atomically.
- Repository layout uses separate repos: this package repo (src layout) and the sample project in the sibling `agentic-django-example` repo (apps under `agentic-django-example/apps/`).
- Sample Docker Compose stack uses Postgres + Redis + RQ (via django-tasks) for production-like orchestration.
