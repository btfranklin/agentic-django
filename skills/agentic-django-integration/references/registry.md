# Agent Registry

Provide a callable that returns a mapping of agent keys to factory functions.

```python
from agents import Agent


def get_agent_registry():
    def build_default():
        return Agent(
            name="Support Agent",
            instructions="Help the user with account issues.",
        )

    return {"default": build_default}
```

Settings:

```python
AGENTIC_DJANGO_AGENT_REGISTRY = "my_project.agent_registry.get_agent_registry"
AGENTIC_DJANGO_DEFAULT_AGENT_KEY = "default"
```
