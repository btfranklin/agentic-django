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
  hx-get="{% url 'agents:run-fragment' run.id %}"
  hx-trigger="load delay:1s, every 2s"
  hx-target="#run-container-{{ run.id }}"
  hx-swap="outerHTML"
>
  {% load agentic_django_tags %}
  {% agent_run_fragment run %}
</div>
```
