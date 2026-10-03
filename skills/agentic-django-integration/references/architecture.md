# Architecture Overview

Agentic Django submits work through Django tasks. A background backend runs it
in a worker. The immediate backend runs it in the submitting process.
The high-level flow is:

1. The submission view validates input and calls `submit_agent_run`, which creates
   an `AgentRun` row with `status="pending"`.
2. The run is enqueued via Django tasks (Immediate or RQ backend).
3. The task executes `Runner.run` through the process's shared async bridge or
   `Runner.run_streamed` (sync return) when events are enabled.
4. The run row is updated with `final_output`, `raw_responses`, and status.
5. HTMX or API clients poll the status/fragment endpoints.

SDK execution and async session reads share one event loop per process. This
allows async clients to reuse connections across calls. Thread-sensitive Django
database work still runs on the calling worker thread. A fork starts a new bridge.
The immediate backend drains nested submissions in a loop so large backlogs do
not cause recursive task execution.

A failure to dispatch later work is logged. It does not change the current run's
outcome. SDK approval interruptions mark a run failed; the package has no approval
or resume endpoint. A host that needs paused approvals must store and resume SDK
state through its own workflow.

## Event streaming

When events are enabled, the runner returns a `RunResultStreaming` object.
Events are consumed via the async generator `RunResultStreaming.stream_events()`.
The default event serializer stores semantic events and skips raw token events.

## Concurrency and dispatch

Pending runs are dispatched up to `AGENTIC_DJANGO_CONCURRENCY_LIMIT`.
Dispatch uses database locking to avoid race conditions and then enqueues tasks
after commit to keep transactions short. Only one run per session executes at a
time. Each run reads the history present when it starts. This does not guarantee
submission-order execution across queue workers. Different sessions can execute
concurrently.

## Run recovery

Recovery is manual and requires stopped workers and paused submissions. Process
startup does not change existing run status. To recover abandoned pending
reservations, use `--include-pending` after removing affected old tasks from the
queue. See [operations](operations.md) for the procedure.

## Session data

The conversation tag and history endpoint read the configured session backend.
Cleanup applies only to local records. The host app owns external history
retention.

## Custom submission

Use `agentic_django.services.submit_agent_run` with keyword arguments `owner`,
`session_key`, `agent_key`, `input_payload`, and optional `metadata`. Authenticate
the caller, validate input, select an allowed agent, and apply request limits
before this call. The service owns session locking, backend initialization,
local record creation, and enqueue after commit. Use this service instead of
copying the database transaction into a custom view.

An outer rollback discards local records and the enqueue callback. External
backend effects are outside that transaction. Queue failure after commit leaves
the run stored for retry. Query the run status for its current state.
