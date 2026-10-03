# Agentic Django

![Agentic Django banner](https://raw.githubusercontent.com/btfranklin/agentic-django/main/.github/social%20preview/agentic_django_social_preview.jpg "Agentic Django")

Agentic Django is a reusable Django 6 app that wraps the OpenAI Agents SDK with
Django-friendly primitives (sessions, runs, and background tasks). The example
project lives in the sibling `agentic-django-example` repo.

## Requirements

- Python 3.12+
- Django 6.1 or later; the current target is Django 6.x.

## Quickstart

Start with an existing Django project that has authentication and session
middleware configured. Replace `my_project` below with your project package name.

### 1. Install the package

```bash
pdm add agentic-django
```

For the default OpenAI provider, set `OPENAI_API_KEY` in the environment used by
your Django process. The package does not load `.env` files itself.

### 2. Define the agent registry

Create `my_project/agent_registry.py`:

```python
from collections.abc import Callable

from agents import Agent


def build_default() -> Agent:
    return Agent(name="Support Agent")


def get_agent_registry() -> dict[str, Callable[[], Agent]]:
    return {"default": build_default}
```

This minimal agent uses the SDK's default model. Add your agent instructions,
model, and tools in `build_default` when you extend the integration.

### 3. Configure the app and local execution

Add these entries to `settings.py`:

```python
INSTALLED_APPS = [
    # Keep your existing apps.
    "agentic_django.apps.AgenticDjangoConfig",
]

AGENTIC_DJANGO_AGENT_REGISTRY = "my_project.agent_registry.get_agent_registry"
AGENTIC_DJANGO_DEFAULT_AGENT_KEY = "default"

TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
    }
}
```

The immediate backend runs the agent during the request. It needs no worker and
is useful for a first local run. Use a background task backend for production.

### 4. Add the URLs and run migrations

Add the package URLs to your project's `urls.py`:

```python
from django.urls import include, path

urlpatterns = [
    # Keep your existing URL patterns.
    path("agents/", include("agentic_django.urls", namespace="agents")),
]
```

```bash
pdm run python manage.py migrate
pdm run python manage.py runserver
```

### 5. Submit a run and read its result

From an authenticated client, send a JSON request to `POST /agents/runs/`.
Include the session cookie and a valid CSRF token, as required by your project.

```json
{
  "session_key": "first-conversation",
  "input": "Hello"
}
```

The response contains a `run_id`. Request `GET /agents/runs/<run_id>/` to read
its `status` and `final_output`. With a background backend, repeat that request
until the status is `completed` or `failed`.

The JSON endpoints need no HTMX setup. Continue with [HTMX](#htmx) for HTML
polling, [optional configuration](#optional-configuration) for background tasks
and limits, or [usage examples](#usage-examples) for custom views.

## Repository docs

Maintainers and coding agents should start with `docs/index.md`. The current
architecture map lives in `docs/architecture.md`, validation guidance lives in
`docs/quality.md`, and the embedded downstream-integration skill is documented
in `docs/skills.md`.

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

Use `submit_agent_run` after authentication and input validation. It creates the
run and submits the task after the database transaction commits:

```python
from django.http import HttpRequest, JsonResponse

from agentic_django.services import submit_agent_run


def submit_run(request: HttpRequest) -> JsonResponse:
    run = submit_agent_run(
        owner=request.user,
        session_key=request.POST["session_key"],
        agent_key="default",
        input_payload=request.POST["input"],
    )
    return JsonResponse({"run_id": str(run.id), "status": run.status})
```

The service initializes the configured session backend, locks session reuse
against cleanup, and creates the local session and run records. It accepts
optional `metadata` for context and run options. The caller must validate the
input, select an allowed agent key, and apply any request limits. The built-in
creation view performs these HTTP checks before calling the same service.

An outer transaction delays enqueue until its commit. If it rolls back, the
local records and queue callback are discarded. External backend effects cannot
be rolled back by the database transaction. Queue submission can fail after
commit; the run remains stored for retry. Read the status endpoint for the
current run state, including when an immediate task backend is used.

Check run status later from a UI or API client:

```python
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from agentic_django.models import AgentRun

def run_status(request, run_id):
    run = get_object_or_404(AgentRun, id=run_id, owner=request.user)
    return JsonResponse({
        "status": run.status,
        "final_output": run.final_output,
    })
```

## HTMX

If you are using the package's HTMX-oriented views and fragments, add
`django-htmx` to your project so requests expose `request.htmx` and you can use
the vendored script tags with Django 6 CSP nonces:

```python
INSTALLED_APPS = [
    # ...
    "django_htmx",
    "agentic_django.apps.AgenticDjangoConfig",
]

MIDDLEWARE = [
    # ...
    "django_htmx.middleware.HtmxMiddleware",
]
```

```html
{% load django_htmx static %}
<link rel="stylesheet" href="{% static 'agentic_django/agentic_django.css' %}">
{% htmx_script %}
{% django_htmx_script %}
```

If you are only using the JSON endpoints, you can omit `django_htmx` and its
middleware.

HTMX polling + coordinated updates:

```html
{% load agentic_django_tags %}
{% agent_run_fragment run %}
```

The tag renders the complete run container and its polling attributes. Do not
wrap it in another element with the same ID or polling attributes.

The fragment endpoint returns `HttpResponseStopPolling` when a run reaches a
terminal state, so HTMX swaps in the final HTML and stops polling without extra
client-side teardown code.

The package's fragment responses also emit `HX-Trigger: run-update` on each
refresh so dependent panels can piggyback on the run poll loop instead of
starting their own:

```python
# Implemented in the package's fragment views.
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

Template override note: if you create `templates/agentic_django/...` in your project, Django will use those files instead of the package templates with the same path. This is useful for customization, but it can hide edits made in the package templates.

## Styling (optional)

The package ships a minimal stylesheet for the default fragments. If you are not
already including it via the HTMX setup above, add it to your base template:

```html
{% load static %}
<link rel="stylesheet" href="{% static 'agentic_django/agentic_django.css' %}">
```

## Optional configuration

After the quickstart works, configure run limits and a background backend in
`settings.py` as needed. Install the RQ extra with `pdm add "agentic-django[rq]"`.
The RQ backend also needs Redis and a running RQ worker. Add both `django_rq` and
`django_tasks_rq` to `INSTALLED_APPS`.

```python
AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS = {"max_turns": 6}
AGENTIC_DJANGO_CONCURRENCY_LIMIT = None  # auto: CPU count

RQ_QUEUES = {
    "default": {
        "URL": "redis://localhost:6379/0",
    }
}

# Switch to RQ-backed tasks in production
TASKS["default"] = {
    "BACKEND": "django_tasks_rq.RQBackend",
    "QUEUES": ["default"],
}

# Optional: enable event streaming persistence
AGENTIC_DJANGO_ENABLE_EVENTS = True

# Optional: basic abuse protection for run creation
AGENTIC_DJANGO_RATE_LIMIT = "20/m"
AGENTIC_DJANGO_MAX_INPUT_BYTES = 20_000
AGENTIC_DJANGO_MAX_INPUT_ITEMS = 20

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

Start the worker with the task-specific job class:

```bash
pdm run python manage.py rqworker default --job-class django_tasks_rq.Job
```

Request limits use one database counter per user. Atomic updates enforce the
limit across workers, without a cache dependency. Run migrations before use.
Limits also support custom user primary keys. The concurrency limit must be a
positive integer or `None`; invalid values stop app startup.

Run creation rejects non-finite JSON numbers and decoded JSON documents with
more than 100 nested arrays or objects. This check applies to JSON request bodies
and to JSON decoded from form `config` and `context` fields. Input text is stored
as text.

SDK calls use one event loop per process so shared async clients can reuse their
connections. The package does not provide tool approval or resume endpoints.
If the SDK returns pending approvals, the run is marked failed. See the SDK's
[tool approval guide](https://openai.github.io/openai-agents-python/human_in_the_loop/)
when a host application needs approval and resume support.

## Optional dependencies

- RQ-backed tasks in a host project: `pdm add "agentic-django[rq]"`
- RQ validation in this repository: `pdm install -G dev -G rq`
- Postgres driver in a host project: `pdm add "agentic-django[postgres]"`

## Event streaming (optional)

When `AGENTIC_DJANGO_ENABLE_EVENTS = True`, each agent run persists semantic events
(tool calls, tool outputs, message items). Poll for events with:

```
GET /agents/runs/<uuid:run_id>/events/?after=<sequence>&limit=<n>
```

You can also subscribe to the Django signal `agent_run_event` to push UI updates
after each event is stored.

## Operations

Prune old data with the cleanup command (uses `AGENTIC_DJANGO_CLEANUP_POLICY` by default):

```bash
python manage.py agentic_django_cleanup --dry-run
python manage.py agentic_django_cleanup --events-days 14 --runs-days 60
```

Cleanup affects local database records only. It does not inspect or remove
history in an external session backend. `sessions_require_empty` checks local
runs and items. Sessions with pending or running work are retained, including
when nonempty cleanup is enabled. The host app must manage external history
retention.

Recover runs stuck in `running` after a restart:

```bash
python manage.py agentic_django_recover_runs --mode=fail
python manage.py agentic_django_recover_runs --mode=requeue
```

Recovery is manual. Stop all run workers and pause submissions before recovery.
A new process must not reset work that another worker still executes. The
`AGENTIC_DJANGO_STARTUP_RECOVERY` setting has been removed. Requeue only when
repeating the run and its tool actions is safe.

If submission stopped after reserving a pending run, use `--include-pending`.
This includes all pending runs with queue reservations or task IDs. Stop workers,
pause submissions, and remove the affected old tasks from the queue first.
Without this flag, recovery leaves pending reservations unchanged.

```bash
python manage.py agentic_django_recover_runs --mode=requeue --include-pending
```

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
