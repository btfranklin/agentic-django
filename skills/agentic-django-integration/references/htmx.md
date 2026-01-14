# HTMX Usage

## Submission form

```html
<form
  hx-post="/agents/runs/"
  hx-target="#run-container"
  hx-swap="outerHTML"
>
  <input type="hidden" name="session_key" value="{{ session_key }}" />
  <textarea name="input"></textarea>
  <button type="submit">Run</button>
</form>
```

## Polling fragment

```html
<div
  id="run-container-{{ run.id }}"
  data-status="{{ run.status }}"
  hx-get="{% url 'agents:run-fragment' run.id %}"
  hx-trigger="load delay:1s, every 2s"
  hx-target="#run-container-{{ run.id }}"
  hx-swap="outerHTML"
  hx-on::afterSwap="if (this.dataset.status === 'completed' || this.dataset.status === 'failed') { this.removeAttribute('hx-get'); this.removeAttribute('hx-trigger'); }"
>
  {% load agentic_django_tags %}
  {% agent_run_fragment run %}
</div>
```

## Server-driven coordination

Use `HX-Trigger` to update dependent panels (conversation, logs, etc.) whenever the run fragment refreshes. This avoids separate polling loops that can restart unexpectedly.

```python
# views.py
response = render(request, "agentic_django/partials/run_fragment.html", {"run": run})
response["HX-Trigger"] = "run-update"
return response
```

```html
<div id="conversation-panel"
     hx-get="{% url 'agents:session-items' session.session_key %}"
     hx-trigger="run-update from:body"
     hx-target="#conversation-contents"
     hx-swap="innerHTML">
  ...
</div>
```

## Template override note

If your project defines `templates/agentic_django/...`, Django will use those files instead of the package templates with the same path. This is useful for customization, but it can mask edits in the package templates.

## Gotchas

- **Multiple polling loops**: avoid combining HTMX polling, custom JS timers, and `hx-trigger="load, every ..."` on the same panel. Pick a single source of truth.
- **Swapped targets disappear**: if the element with `hx-target` gets replaced, later requests may fail silently. Keep a stable wrapper element.
- **HTMX error swaps**: HTMX does not swap on 4xx/5xx by default; return a 200 with error HTML for fragment updates.
