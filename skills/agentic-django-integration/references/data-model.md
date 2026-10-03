# Data Model Notes

## AgentSession

- Identified by `session_key` and scoped to `owner`.
- Stores metadata and timestamps.
- The default backend stores history in `AgentSessionItem` rows ordered by `sequence`.

## AgentSessionItem

- `sequence` is unique within a session. Reads use sequence order.
- Appends start after the highest remaining sequence. Removing the last item or
  clearing history can allow sequence values to be reused.
- `payload` is JSON-safe and normalized via the session item serializer
  (default: `SessionItemSerializer`).

## AgentRun

- Tracks one submitted run, executed with `Runner.run` or `Runner.run_streamed`.
- Tracks `status` (`pending`, `running`, `completed`, `failed`), timestamps, and
  execution metadata such as `task_id`.
- Stores `final_output`, `raw_responses`, and `last_response_id`.
- Model validation requires the run owner to match the session owner.
- The default serializer uses Pydantic JSON mode for model values. Dates,
  times, decimals, and UUIDs are stored as JSON-compatible values. Nullable
  fields retain their explicit `null` values.

## AgentEvent (optional)

- Persists semantic stream events when `AGENTIC_DJANGO_ENABLE_EVENTS = True`.
- Each event has a `sequence` and JSON-safe `payload`.

## AgentRequestLimit

- Stores one request counter and window start time per owner.
- Conditional database updates enforce the configured request limit.
- Deleting the owner also deletes the counter.

## Session backends

- Default: `DatabaseSession`, backed by `AgentSessionItem` rows.
- Alternate backends (e.g., Redis) can be used by setting
  `AGENTIC_DJANGO_SESSION_BACKEND`. The `AgentSession` row still exists for
  ownership and run tracking.
