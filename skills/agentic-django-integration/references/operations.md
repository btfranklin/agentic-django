# Operations and Retention

## Cleanup policy

Configure retention windows in settings:

```python
AGENTIC_DJANGO_CLEANUP_POLICY = {
    "events_days": 7,
    "runs_days": 30,
    "runs_statuses": ["completed", "failed"],
    "sessions_days": 90,
    "sessions_require_empty": True,
    "batch_size": 500,
}
```

Run the cleanup command:

```bash
python manage.py agentic_django_cleanup --dry-run
python manage.py agentic_django_cleanup --events-days 14 --runs-days 60
```

## Startup recovery

Handle runs that were `running` during a restart:

```python
AGENTIC_DJANGO_STARTUP_RECOVERY = "fail"  # default is "requeue"
```

Startup recovery runs the first time a process dispatches or executes a run (so it avoids database work in `AppConfig.ready()`).

Or run it manually:

```bash
python manage.py agentic_django_recover_runs --mode=fail
python manage.py agentic_django_recover_runs --mode=requeue
```

## Abuse protection

```python
AGENTIC_DJANGO_RATE_LIMIT = "20/m"
AGENTIC_DJANGO_MAX_INPUT_BYTES = 20_000
AGENTIC_DJANGO_MAX_INPUT_ITEMS = 20
```
