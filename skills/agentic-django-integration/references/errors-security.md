# Errors and Security

## Error handling

- Agent execution errors mark runs as `failed`.
- SDK results with pending approval interruptions also mark runs as `failed`.
  The package does not provide approval or resume endpoints.
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
Custom user primary keys are supported. Multipart byte limits use the request's
content length, so CSRF parsing does not require the body to be read again.

Each decoded request JSON document can contain at most 100 nested arrays or
objects. Non-finite numbers and excessive nesting return HTTP 400 before records
are created. JSON request bodies and decoded form `config` and `context` fields
use the same checks. Literal input text remains text.

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
Existing runs are read-only in admin; create them through the submission service.
Admin cannot save existing runs over worker results. Requeue remains available
to users with run change permission.
Existing session owners and keys are read-only so active workers keep the same
session identity.
