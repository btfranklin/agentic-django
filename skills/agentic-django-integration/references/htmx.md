# HTMX Usage

## Submission form

The `session_key` must contain 1-255 ASCII letters, digits, underscores, or
hyphens. This matches the session history URL. Keys remain scoped to the user.

The `input` form field is plain text. Text that resembles JSON stays unchanged.
To submit structured input items, send an `application/json` request with an
`input` array. JSON request fields are decoded once. The `config` and `context`
form fields can contain JSON.

```html
<form
  hx-post="/agents/runs/"
  hx-target="#run-container"
  hx-swap="innerHTML"
  method="post"
>
  {% csrf_token %}
  <input type="hidden" name="session_key" value="{{ session_key }}" />
  <textarea name="input"></textarea>
  <button type="submit">Run</button>
</form>
<div id="run-container"></div>
```

## Polling fragment

```html
{% load agentic_django_tags %}
{% agent_run_fragment run %}
```

The tag renders the complete run container. Pending and running fragments have
polling attributes. Terminal HTMX responses use `HttpResponseStopPolling` and
omit those attributes. No inline JavaScript is required to stop polling.

## Server-driven coordination

Use `HX-Trigger` to update dependent panels (conversation, logs, etc.) whenever the run fragment refreshes. This avoids separate polling loops that can restart unexpectedly.

```python
from django.shortcuts import render
from django_htmx.http import trigger_client_event

response = render(request, "agentic_django/partials/run_fragment.html", {"run": run})
return trigger_client_event(response, "run-update")
```

```html
<div id="conversation-panel"
     hx-get="{% url 'agents:session-items' session.session_key %}"
     hx-trigger="run-update from:body"
     hx-target="#conversation-contents"
     hx-swap="innerHTML">
  <div id="conversation-contents"></div>
</div>
```

## Template override note

If your project defines `templates/agentic_django/...`, Django will use those files instead of the package templates with the same path. This is useful for customization, but it can mask edits in the package templates.

## Gotchas

- **Multiple polling loops**: avoid combining HTMX polling, custom JS timers, and `hx-trigger="load, every ..."` on the same panel. Pick a single source of truth.
- **Swapped targets disappear**: if the element with `hx-target` gets replaced, later requests may fail silently. Keep a stable wrapper element.
- **HTMX error swaps**: HTMX does not swap on 4xx/5xx by default; return a 200 with error HTML for fragment updates.

The `agent_conversation` tag and session history endpoint both read the configured
session backend. Add `django_htmx` and its middleware as shown in the README.
