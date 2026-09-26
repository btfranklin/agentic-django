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

Cleanup locks each batch and checks eligibility again before deletion. Sessions
with pending or running work are retained, including with nonempty cleanup.
Retention applies only to local database rows. `sessions_require_empty` checks
local runs and items; it does not inspect external history. The host app must
manage retention in an external session backend.

## Run recovery

Stop all run workers and pause submissions before manual recovery. Do not infer
that a run has stopped from a new process starting. Requeue only when repeating
the run and its tool actions is safe.

```bash
python manage.py agentic_django_recover_runs --mode=fail
python manage.py agentic_django_recover_runs --mode=requeue
```

To recover a pending run whose queue submission was interrupted, add
`--include-pending`. This includes all pending rows with reservations or task
IDs. Stop workers and submissions, then remove the affected old tasks from the
queue before using this option. Default recovery leaves pending rows unchanged.

```bash
python manage.py agentic_django_recover_runs --mode=requeue --include-pending
```

## RQ setup

Install the extra in the host project with `pdm add "agentic-django[rq]"`. Add
`django_rq` and `django_tasks_rq` to `INSTALLED_APPS`, configure `RQ_QUEUES`, and
set the task backend to `django_tasks_rq.RQBackend`. Start the worker with:

```bash
pdm run python manage.py rqworker default --job-class django_tasks_rq.Job
```

See the repository README for the full settings example.

## Abuse protection

```python
AGENTIC_DJANGO_RATE_LIMIT = "20/m"
AGENTIC_DJANGO_MAX_INPUT_BYTES = 20_000
AGENTIC_DJANGO_MAX_INPUT_ITEMS = 20
```
