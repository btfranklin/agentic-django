# Architecture

Agentic Django is a reusable Django 6 app that persists OpenAI Agents SDK
sessions, dispatches agent runs through Django tasks, and exposes owner-scoped
JSON and HTMX polling endpoints.

## Package Surface

| Area | Files | Responsibility |
| --- | --- | --- |
| App config | `src/agentic_django/apps.py` | Registers the Django app and validates settings during app startup. |
| Settings | `src/agentic_django/conf.py` | Reads and validates `AGENTIC_DJANGO_*` settings, cleanup policy, rate limits, and concurrency limits. |
| Async bridge | `src/agentic_django/async_bridge.py` | Runs async SDK and session calls on one event loop per process. Preserves database work on the calling worker thread. |
| Models | `src/agentic_django/models.py` | Stores sessions, ordered session items, runs, semantic events, per-owner request counters, and a global dispatch lock row. |
| Session backend | `src/agentic_django/sessions.py` | Implements the Agents SDK session protocol with ordered database-backed items. |
| Registry | `src/agentic_django/registry.py` | Loads the host app's agent factory registry and resolves `agent_key` values. |
| Serializers | `src/agentic_django/serializers.py` | Normalizes SDK results, session items, and semantic stream events into JSON-safe payloads. |
| Services | `src/agentic_django/services.py` | Submits runs, dispatches pending work, executes SDK runs, persists outputs/events, sends signals, and recovers stuck runs. |
| Tasks | `src/agentic_django/tasks.py` | Defines the Django task entry point that calls `execute_run`. |
| Request limits | `src/agentic_django/rate_limits.py` | Reserves requests with conditional database updates to one counter per owner. |
| Views and URLs | `src/agentic_django/views.py`, `src/agentic_django/urls.py` | Provide authenticated run creation, status, fragment, event, and session-history endpoints. |
| Templates and CSS | `src/agentic_django/templates/agentic_django/`, `src/agentic_django/static/agentic_django/` | Ship default HTMX fragments and minimal package styling. |
| Operations | `src/agentic_django/management/commands/` | Provides cleanup and run-recovery commands. |

## Runtime Flow

1. `AgentRunCreateView` authenticates the user, validates payload shape and
   limits, resolves the agent key, and calls `submit_agent_run`.
2. `submit_agent_run` locks session reuse, initializes the configured backend,
   and creates the local session and run in one transaction. It calls
   `enqueue_agent_run` to schedule `run_agent_task` after commit and store its
   task ID. Custom submission paths use this same service.
3. `execute_run` reserves a global concurrency slot and exclusive session access, sends `agent_run_started`, builds
   the agent/session/context/run options, and calls the Agents SDK runner.
4. If events are disabled, `Runner.run` is executed through the async bridge.
   If events are enabled, `Runner.run_streamed` is used and semantic
   `RunItemStreamEvent`/`AgentUpdatedStreamEvent` payloads are persisted.
   The default event serializer skips raw token events.
5. Completion serializes the result and saves `final_output`,
   `raw_responses`, `last_response_id`, and completed status, clears the task ID,
   then sends `agent_run_completed` and releases agent references.
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
  replaced with a generic message. Full exception text stays in server logs.
- Rate limits and request-size/input-item limits are enforced before run
  creation when configured.
- JSON numbers must be finite. Each decoded request JSON document can contain
  at most 100 nested arrays or objects. Invalid values return HTTP 400 before
  local records are created.
- Agent registries are host-app supplied. Do not expose powerful tools to
  untrusted input without host-app validation or allowlists.

Request limits use `AgentRequestLimit`, with one row per owner. A conditional
update resets an expired window. A second conditional update increments the
count only when it is below the limit. Its affected-row count decides admission.
These database operations enforce the limit across workers without cache or
`select_for_update` assumptions. Deleting the owner removes the counter.

## Dependency Direction

Keep dependencies mostly one-way:

- `models.py` should not import views, tasks, services, registry code, or
  serializers.
- `serializers.py` should stay framework-light and avoid importing models,
  services, tasks, or views.
- `rate_limits.py` may depend on models and Django database operations.
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

## Lifecycle notifications

Run signals are notifications. Receiver exceptions are logged and do not change
run status or prevent other receivers from running. Event persistence saves each
event and sends its notification in the same helper. Setup failures within the
executor mark the run failed and release its slot. `agent_session_created` uses
normal signal dispatch; a receiver exception propagates to its caller.

## Async execution

SDK calls and session reads use one event loop per process. The loop starts in a
background thread on the first call. It remains open so shared async clients can
reuse their connections. The bridge uses `async_to_sync` on that running loop;
thread-sensitive database calls return to the calling worker thread. Concurrent
workers can submit separate runs to the same loop. The bridge restores the
caller's ASGI loop and task state when each call ends. A fork starts a new bridge
in the child process.

When event consumption fails, execution cancels the SDK stream and waits for its
cleanup before releasing the session slot. A failure to dispatch later work is
logged and does not replace the completed or failed outcome of the current run.
A cancelled SDK run task marks a streamed run failed, even when the event stream
ends without an exception.

The package has no tool approval or resume endpoint. A returned SDK result with
pending approval interruptions marks the run failed. It must not be reported as
completed. Host applications must resolve approval within their tool integration
or use a workflow that stores and resumes the SDK state.

## Queue reservations

Initial enqueue and pending dispatch use the same queue submission helper. Each
reservation has a unique token. On queue failure, the helper releases the failed
reservation and the unsent part of its batch. These runs remain eligible for the
next dispatch. Completion or rejection by an immediate worker cannot restore an
obsolete reservation. Submission uses the decorated Django task's `enqueue()`
method and stores the returned `TaskResult.id`. Dispatch selects one eligible
row per free slot with a bounded query. It does not load the full pending queue.
Nested submissions from the immediate backend join the caller's submission
queue. The outer caller drains that queue in a loop, which prevents stack growth
when a completed run dispatches the next run. A queue failure releases all
unsent reservations held by that caller.

## Session execution

Only one run per session can have `running` status. Dispatch and execution check
this rule under the dispatch lock. A write to the lock row starts the transaction
before any run reads, which also serializes SQLite workers. A database constraint
also enforces the session rule.
The reservation covers history reads and writes for the complete run. Database
transactions end before the model call. Other sessions can run concurrently.

Stop workers and recover existing running rows before applying the session
constraint migration if a session has more than one running row.

## Recovery

Recovery is an explicit maintenance operation. Stop workers and pause submissions
before recovery. Process startup does not reset active runs. Requeue can repeat
tool actions, so the operator must check that repetition is safe.

By default, recovery handles running rows only. `--include-pending` also handles
pending rows with a reservation or task ID. Use it after an interrupted queue
submission. Remove affected old tasks from the queue before this operation;
requeue clears the stored reservation and submits replacement work.

## Cleanup and session reuse

Cleanup selects candidate IDs in batches. Each batch locks its rows, then checks
age, status, and emptiness again before deletion. Session batches also lock their
child runs. Session cleanup retains pending and running work even when nonempty
cleanup is enabled.

`submit_agent_run` touches the session in a transaction before it creates the
run. History changes also write the parent session first. These writes serialize
with cleanup on SQLite and on databases with row locks. Custom submission code
calls `submit_agent_run` rather than repeating this lock and creation sequence.

The service accepts validated input, an owner, a session key, an allowed agent
key, and optional metadata. Authentication, payload validation, and request
limits belong to its caller. Local record changes roll back together; enqueue
waits for the outermost transaction to commit. External backend effects are
outside the database transaction. A queue failure after commit leaves the run
stored for retry. The returned model is the creation snapshot; query the run
again for its current status.

Retention applies only to local database records. For an external session
backend, `sessions_require_empty` checks only local runs and items. Cleanup does
not read or delete external history. The host app owns that retention policy.

The conversation template tag and history endpoint both read the configured
session backend. They pass the returned items to the same conversation template.

## Admin permissions

The requeue action requires run change permission. The purge action requires run
delete permission. View permission alone does not permit either action.
Model validation rejects a run whose owner differs from its session owner. It
also rejects a session owner change that conflicts with existing runs. Admin
search uses fields from the configured user model.
Existing run records are read-only in admin. Object saves are disabled so a form
cannot overwrite worker results. Create runs through the submission service and
use the requeue action for retries. Existing session owners and keys
are also read-only, so edits cannot change the identity used by an active worker.

## Current Limits

- The package uses polling; it does not ship SSE or WebSocket push.
- The default session backend is database-backed. Alternative backends must
  satisfy the Agents SDK session protocol and preserve owner scoping.
- Celery is not part of the package contract. Use Django tasks and configure an
  RQ-backed task backend when production-like background workers are needed.
- OpenAI server-managed conversations are not the core storage model; local
  sessions are the default for provider-agnostic reuse.
