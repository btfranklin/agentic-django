# Data Model Notes

## AgentSession

- Identified by `session_key` and scoped to `owner`.
- Stores metadata and timestamps.
- Conversation history is stored in `AgentSessionItem` rows ordered by `sequence`.

## AgentSessionItem

- `sequence` is monotonic per session; ordering is enforced by DB constraints.
- `payload` is JSON-safe and normalized via the session item serializer
  (default: `SessionItemSerializer`).

## AgentRun

- Represents a single `Runner.run` invocation.
- Tracks `status` (`pending`, `running`, `completed`, `failed`), timestamps, and
  execution metadata such as `task_id`.
- Stores `final_output`, `raw_responses`, and `last_response_id`.

## AgentEvent (optional)

- Persists semantic stream events when `AGENTIC_DJANGO_ENABLE_EVENTS = True`.
- Each event has a `sequence` and JSON-safe `payload`.

## Session backends

- Default: `DatabaseSession`, backed by `AgentSessionItem` rows.
- Alternate backends (e.g., Redis) can be used by setting
  `AGENTIC_DJANGO_SESSION_BACKEND`. The `AgentSession` row still exists for
  ownership and run tracking.
