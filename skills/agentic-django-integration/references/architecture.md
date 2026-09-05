# Architecture Overview

Agentic Django runs agent work outside the request/response cycle using Django tasks.
The high-level flow is:

1. Submission view validates input and creates an `AgentRun` row with `status="pending"`.
2. The run is enqueued via Django tasks (Immediate or RQ backend).
3. The task executes `Runner.run` (async; wrapped with `async_to_sync`) or
   `Runner.run_streamed` (sync return) when events are enabled.
4. The run row is updated with `final_output`, `raw_responses`, and status.
5. HTMX or API clients poll the status/fragment endpoints.

## Event streaming

When events are enabled, the runner returns a `RunResultStreaming` object.
Events are consumed via the async generator `RunResultStreaming.stream_events()`.
Only semantic events are stored; raw response token events are skipped.

## Concurrency and dispatch

Pending runs are dispatched up to `AGENTIC_DJANGO_CONCURRENCY_LIMIT`.
Dispatch uses database locking to avoid race conditions and then enqueues tasks
after commit to keep transactions short.

## Run recovery

Recovery is manual and requires stopped workers and paused submissions. Process
startup does not change existing run status.
