# Event Streaming

## Enable events

```python
AGENTIC_DJANGO_ENABLE_EVENTS = True
```

## Polling endpoint

```
GET /agents/runs/<uuid:run_id>/events/?after=<sequence>&limit=<n>
```

Returns:

```json
{
  "run_id": "uuid",
  "events": [
    {
      "sequence": 12,
      "event_type": "tool_called",
      "payload": {
        "type": "run_item_stream_event",
        "name": "tool_called"
      },
      "created_at": "2025-02-18T23:41:12.123456+00:00"
    }
  ]
}
```

## Signal hook

Subscribe to the Django signal after each event is stored:

```python
from agentic_django.signals import agent_run_event


def handle_event(sender, run, event, sequence, event_type, payload, **kwargs):
    ...


agent_run_event.connect(handle_event, weak=False)
```
