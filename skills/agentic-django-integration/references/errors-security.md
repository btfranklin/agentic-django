# Errors and Security

## Error handling

- Agent execution errors mark runs as `failed`.
- When `DEBUG=True`, error payloads include full tracebacks.
- When `DEBUG=False`, errors are sanitized to `ClassName: message`.

## Ownership and access

- All run/session queries must be filtered by `owner` to prevent cross-user access.
- Session keys are scoped per user.

## Abuse protection

- Optional throttling and payload limits:
  - `AGENTIC_DJANGO_RATE_LIMIT`
  - `AGENTIC_DJANGO_MAX_INPUT_BYTES`
  - `AGENTIC_DJANGO_MAX_INPUT_ITEMS`

## Content Security Policy

- Prefer Django 6 CSP support when embedding polling or tool-driven UIs.
- Open `connect-src` only to required endpoints.

## Tool safety

- Avoid exposing powerful tools to untrusted input without allowlists or validation.
