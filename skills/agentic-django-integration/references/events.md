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

The event and session history endpoints accept a non-negative integer `limit`.
A limit of zero returns no items. Invalid and negative limits return HTTP 400.
Limits above `2**63 - 1` also return HTTP 400.

Semantic events are saved as they arrive. A later stream failure does not discard
events that were already received. Signals run after the database write and can
use the synchronous Django ORM.
If event storage fails, the SDK stream is cancelled and closed before the run
releases its session slot.
A cancelled SDK run task marks the run failed, even if its event stream ends
without an exception.

The default serializer skips raw token events. Custom serializers control their
own filtering. Event receivers use robust signal dispatch: receiver exceptions
are logged, and other receivers still run. This behavior differs from
`agent_session_created`, which uses normal signal dispatch.
