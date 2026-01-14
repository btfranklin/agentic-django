# Agentic Django

Agentic Django is a reusable Django 6 app that wraps the OpenAI Agents SDK with
Django-friendly primitives (sessions, runs, and background tasks). The example
project lives in the sibling `agentic-django-example` repo.

## Why use it

Building agentic workflows in Django usually means stitching together the OpenAI
Agents SDK, persistence, and async execution on your own. This project gives you
a consistent, Django-native way to:

- kick off multi-step agent runs from views or services
- persist conversation history and run status in your database
- check progress later from any UI or API client
- keep runs private to each authenticated user
- reuse the same primitives across multiple apps or projects

## Benefits

- Django-first integration with models, admin, templates, and URL patterns
- simple async model using Django 6 tasks (no Celery required)
- stable polling UX for HTMX or REST clients
- per-user ownership baked into queries and views
- flexible registry so each project can provide its own agents

## How it helps

If you have a workflow that can take minutes, branch into tools, or write to
session memory, you can run it as a background task and poll for status just
like any other Django async job. You do not need to keep a request open or build
custom state tracking.

## Usage examples

Create a run from a view and enqueue it for background execution:

```python
from agentic_django.models import AgentRun, AgentSession
from agentic_django.services import enqueue_agent_run

def submit_run(request):
    session, _ = AgentSession.objects.get_or_create(
        owner=request.user,
        session_key=request.POST["session_key"],
    )
    run = AgentRun.objects.create(
        session=session,
        owner=request.user,
        agent_key="demo",
        input_payload=request.POST["input"],
    )
    enqueue_agent_run(str(run.id))
```

Check run status later from a UI or API client:

```python
from django.shortcuts import get_object_or_404
from agentic_django.models import AgentRun

def run_status(request, run_id):
    run = get_object_or_404(AgentRun, id=run_id, owner=request.user)
    return {
        "status": run.status,
        "final_output": run.final_output,
    }
```

HTMX polling in a template:

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

## HTMX cookbook (happy path)

Coordinate panels with `HX-Trigger` so you only update when there is run activity:

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

Stop polling once a run finishes (to avoid pointless requests):

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

Template override note: if you create `templates/agentic_django/...` in your project, Django will use those files instead of the package templates with the same path. This is useful for customization, but it can hide edits made in the package templates.

## Styling (optional)

The package ships a minimal stylesheet for the default fragments. Include it in your base template:

```html
{% load static %}
<link rel="stylesheet" href="{% static 'agentic_django/agentic_django.css' %}">
```

## Configuration

Add the app and configure the agent registry in `settings.py`:

```python
INSTALLED_APPS = [
    # ...
    "agentic_django.apps.AgenticDjangoConfig",
]

AGENTIC_DJANGO_AGENT_REGISTRY = "my_project.agent_registry.get_agent_registry"
AGENTIC_DJANGO_DEFAULT_AGENT_KEY = "default"
AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS = {"max_turns": 6}
AGENTIC_DJANGO_CONCURRENCY_LIMIT = None  # auto: CPU count

# django-tasks backend selection (Immediate by default, RQ in production)
TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
    }
}

RQ_QUEUES = {
    "default": {
        "URL": "redis://localhost:6379/0",
    }
}

# Switch to RQ-backed tasks in production
TASKS["default"]["BACKEND"] = "django_tasks.backends.rq.RQBackend"

# Optional: enable event streaming persistence
AGENTIC_DJANGO_ENABLE_EVENTS = True

# Optional: basic abuse protection for run creation
AGENTIC_DJANGO_RATE_LIMIT = "20/m"
AGENTIC_DJANGO_MAX_INPUT_BYTES = 20_000
AGENTIC_DJANGO_MAX_INPUT_ITEMS = 20

# Optional: override startup recovery (default: requeue)
AGENTIC_DJANGO_STARTUP_RECOVERY = "fail"

# Optional: cleanup policy for old records
AGENTIC_DJANGO_CLEANUP_POLICY = {
    "events_days": 7,
    "runs_days": 30,
    "runs_statuses": ["completed", "failed"],
    "sessions_days": 90,
    "sessions_require_empty": True,
    "batch_size": 500,
}
```

## Optional dependencies

- RQ-backed tasks: `pdm install -G rq`
- Postgres driver: `pdm install -G postgres`

## Event streaming (optional)

When `AGENTIC_DJANGO_ENABLE_EVENTS = True`, each agent run persists semantic events
(tool calls, tool outputs, message items). Poll for events with:

```
GET /runs/<uuid:run_id>/events/?after=<sequence>&limit=<n>
```

You can also subscribe to the Django signal `agent_run_event` to push UI updates
after each event is stored.

Provide a registry that returns agent factories:

```python
from agents import Agent
from my_project.models import MyModelProvider

def get_agent_registry():
    def build_default():
        return Agent(
            name="Support Agent",
            instructions="Help the user with account issues.",
            model=MyModelProvider(),
        )

    return {"default": build_default}
```

## Operations

Prune old data with the cleanup command (uses `AGENTIC_DJANGO_CLEANUP_POLICY` by default):

```bash
python manage.py agentic_django_cleanup --dry-run
python manage.py agentic_django_cleanup --events-days 14 --runs-days 60
```

Recover runs stuck in `running` after a restart:

```bash
python manage.py agentic_django_recover_runs --mode=fail
python manage.py agentic_django_recover_runs --mode=requeue
```

Startup recovery runs on the first run dispatch/execution in each process, so it does
not touch the database during app initialization.

## Security notes

- Enable Django 6’s Content Security Policy support where feasible, and open
  `connect-src` only to the endpoints your UI needs (for polling or tooling).
- Keep agent tool registries scoped; do not expose powerful tools to untrusted
  user input without additional validation or allowlists.

## Example project

The sample project lives in the sibling `agentic-django-example` repo. See its
README for setup, Docker, and run instructions.

## Tests

```bash
pdm run test
```

## License

MIT. See `LICENSE`.
