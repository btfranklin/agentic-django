# Errors and Security

## Error handling

- Agent execution errors mark runs as `failed`.
- When `DEBUG=True`, error payloads include full tracebacks.
- When `DEBUG=False`, users receive a generic failure message. Exception text
  stays in server logs and is not included in the response. Use the run ID to
  find the detailed server error.

## Ownership and access

- Request-facing run/session queries must filter by `owner` to prevent cross-user access.
- Session keys are scoped per user.

## Abuse protection

- Optional throttling and payload limits:
  - `AGENTIC_DJANGO_RATE_LIMIT`
  - `AGENTIC_DJANGO_MAX_INPUT_BYTES`
  - `AGENTIC_DJANGO_MAX_INPUT_ITEMS`

Request limits use one database counter per owner. Conditional database updates
reserve each request, so concurrent workers cannot exceed the configured limit.
The window starts with the first request and resets after the configured period.
Cache settings do not affect request limits.

## Content Security Policy

- Prefer Django 6 CSP support when embedding polling or tool-driven UIs.
- Open `connect-src` only to required endpoints.

## Tool safety

- Avoid exposing powerful tools to untrusted input without allowlists or validation.

## Submission and admin permissions

The built-in create view applies request limits and payload validation. Custom
callers must perform these checks before `submit_agent_run`. The service owns
record creation and queue submission; it does not authenticate callers.

Admin requeue requires run change permission. Purge requires run delete
permission. View permission alone allows neither action.
