# Agentic Django Quickstart

Requires Python 3.12+ and Django 6.1 or later. The current target is Django 6.x.

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

The JSON endpoints need no HTMX setup. Continue with [HTMX](htmx.md) for HTML
polling, [registry guidance](registry.md) for agent factories, or
[operations](operations.md) for limits and maintenance. See the repository
README's optional configuration for the RQ backend setup.
