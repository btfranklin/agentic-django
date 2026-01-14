# Agentic Django Quickstart

## Requirements

- Python 3.12+
- Django 6.x

## Install and configure

1. Add the app:

```python
INSTALLED_APPS = [
    # ...
    "agentic_django.apps.AgenticDjangoConfig",
]
```

2. Add URLs:

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("agents/", include(("agentic_django.urls", "agents"), namespace="agents")),
]
```

3. Configure settings:

```python
AGENTIC_DJANGO_AGENT_REGISTRY = "my_project.agent_registry.get_agent_registry"
AGENTIC_DJANGO_DEFAULT_AGENT_KEY = "default"
AGENTIC_DJANGO_DEFAULT_RUN_OPTIONS = {"max_turns": 6}
AGENTIC_DJANGO_CONCURRENCY_LIMIT = None
```

4. Run migrations:

```bash
python manage.py migrate
```

## Optional: background tasks

```python
TASKS = {
    "default": {
        "BACKEND": "django_tasks.backends.immediate.ImmediateBackend",
    }
}
```

```python
RQ_QUEUES = {
    "default": {
        "URL": "redis://localhost:6379/0",
    }
}
```

```python
TASKS["default"]["BACKEND"] = "django_tasks.backends.rq.RQBackend"
```
