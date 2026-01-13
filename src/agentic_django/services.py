from __future__ import annotations

import logging
import threading
import traceback
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Max
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone
from django.utils.module_loading import import_string

from agents import Runner
from agents.stream_events import RunItemStreamEvent, StreamEvent

from agentic_django.conf import get_concurrency_limit, get_settings
from agentic_django.models import AgentEvent, AgentRun, AgentRunLock
from agentic_django.registry import get_agent
from agentic_django.serializers import JsonSerializer
from agentic_django.sessions import get_session
from agentic_django.signals import (
    agent_run_completed,
    agent_run_event,
    agent_run_failed,
    agent_run_started,
)

logger = logging.getLogger(__name__)
_startup_recovery_done = False
_startup_recovery_in_progress = False
_startup_recovery_lock = threading.Lock()


def enqueue_agent_run(run_id: str) -> None:
    from agentic_django.tasks import run_agent_task

    task_ref = _enqueue_task(run_agent_task, run_id)
    task_id = _extract_task_id(task_ref)
    if task_id:
        AgentRun.objects.filter(id=run_id).update(task_id=task_id, updated_at=timezone.now())


def dispatch_pending_runs() -> int:
    maybe_recover_stuck_runs()
    from agentic_django.tasks import run_agent_task

    limit = get_concurrency_limit()
    with transaction.atomic():
        _lock_guard()
        running_count = AgentRun.objects.filter(status=AgentRun.Status.RUNNING).count()
        available = max(0, limit - running_count)
        if available == 0:
            return 0
        pending_runs = (
            AgentRun.objects.filter(status=AgentRun.Status.PENDING, task_id="")
            .order_by("created_at")
            .select_for_update()
        )[:available]
        enqueued = 0
        for run in pending_runs:
            task_ref = _enqueue_task(run_agent_task, str(run.id))
            task_id = _extract_task_id(task_ref)
            if task_id:
                run.task_id = task_id
                run.save(update_fields=["task_id", "updated_at"])
            enqueued += 1
        return enqueued


def execute_run(run_id: str) -> None:
    maybe_recover_stuck_runs()
    run = AgentRun.objects.select_related("session", "owner").get(id=run_id)
    if run.status != AgentRun.Status.PENDING:
        return
    if not _reserve_run_slot(run):
        AgentRun.objects.filter(id=run_id).update(task_id="", updated_at=timezone.now())
        return

    agent_run_started.send(sender=AgentRun, run=run)
    serializer = _get_serializer()
    try:
        agent = get_agent(run.agent_key)
        session = get_session(run.session.session_key, run.owner)
        run_options = _build_run_options(run)
        context = _build_context(run)
        if get_settings().enable_events:
            result = _run_with_events(
                run=run,
                agent=agent,
                session=session,
                context=context,
                run_options=run_options,
            )
        else:
            result = async_to_sync(Runner.run)(
                agent,
                run.input_payload,
                session=session,
                context=context,
                **run_options,
            )
        run.final_output = serializer.serialize(result.final_output)
        run.raw_responses = serializer.serialize(result.raw_responses)
        run.last_response_id = result.last_response_id or ""
        run.error = ""
        run.task_id = ""
        run.status = AgentRun.Status.COMPLETED
        run.finished_at = timezone.now()
        result.release_agents()
        run.save(
            update_fields=[
                "final_output",
                "raw_responses",
                "last_response_id",
                "error",
                "task_id",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        agent_run_completed.send(sender=AgentRun, run=run, result=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent run failed", extra={"run_id": str(run.id)})
        error = _format_error(exc)
        run.task_id = ""
        run.status = AgentRun.Status.FAILED
        run.error = error
        run.finished_at = timezone.now()
        run.save(
            update_fields=[
                "error",
                "task_id",
                "status",
                "finished_at",
                "updated_at",
            ]
        )
        agent_run_failed.send(sender=AgentRun, run=run, exception=exc)
        raise
    finally:
        dispatch_pending_runs()


def _reserve_run_slot(run: AgentRun) -> bool:
    limit = get_concurrency_limit()
    with transaction.atomic():
        _lock_guard()
        running_count = AgentRun.objects.filter(status=AgentRun.Status.RUNNING).count()
        if running_count >= limit:
            return False
        run.refresh_from_db(fields=["status"])
        if run.status != AgentRun.Status.PENDING:
            return False
        run.status = AgentRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
    return True


def _lock_guard() -> AgentRunLock:
    guard, _ = AgentRunLock.objects.select_for_update().get_or_create(key="global")
    return guard


def _build_run_options(run: AgentRun) -> dict[str, Any]:
    default_options = dict(get_settings().default_run_options)
    run_options = run.metadata.get("run_options", {})
    if not isinstance(run_options, dict):
        return default_options
    default_options.update(run_options)
    return default_options


def _build_context(run: AgentRun) -> Any | None:
    context_factory_path = get_settings().context_factory
    if not context_factory_path:
        return None
    context_factory = import_string(context_factory_path)
    return context_factory(run=run, metadata=run.metadata, owner=run.owner)


def _enqueue_task(task: Any, *args: Any, **kwargs: Any) -> Any:
    if hasattr(task, "enqueue"):
        return task.enqueue(*args, **kwargs)
    if hasattr(task, "delay"):
        return task.delay(*args, **kwargs)
    return task(*args, **kwargs)


def _extract_task_id(task_ref: Any) -> str | None:
    if task_ref is None:
        return None
    for attr in ("id", "task_id"):
        value = getattr(task_ref, attr, None)
        if value:
            return str(value)
    return None


def _format_error(exc: Exception) -> str:
    if django_settings.DEBUG:
        return "".join(traceback.format_exception(exc)).strip()
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _get_serializer() -> JsonSerializer:
    serializer_path = get_settings().serializer
    serializer_cls = import_string(serializer_path)
    return serializer_cls()


def _get_event_serializer() -> Any:
    serializer_path = get_settings().event_serializer
    serializer_cls = import_string(serializer_path)
    return serializer_cls()


def _run_with_events(
    *,
    run: AgentRun,
    agent: Any,
    session: Any,
    context: Any | None,
    run_options: dict[str, Any],
) -> Any:
    event_serializer = _get_event_serializer()
    starting_sequence = _next_event_sequence(run)

    async def _consume() -> Any:
        result = Runner.run_streamed(
            agent,
            run.input_payload,
            session=session,
            context=context,
            **run_options,
        )
        await _consume_stream_events(
            run=run,
            result=result,
            event_serializer=event_serializer,
            starting_sequence=starting_sequence,
        )
        return result

    return async_to_sync(_consume)()


async def _consume_stream_events(
    *,
    run: AgentRun,
    result: Any,
    event_serializer: Any,
    starting_sequence: int,
    batch_size: int = 50,
) -> None:
    sequence = starting_sequence
    batch: list[AgentEvent] = []
    async for event in result.stream_events():
        payload = _serialize_event(event_serializer, event)
        if payload is None:
            continue
        batch.append(
            AgentEvent(
                run=run,
                sequence=sequence,
                event_type=_event_type(event),
                payload=payload,
            )
        )
        sequence += 1
        if len(batch) >= batch_size:
            await sync_to_async(AgentEvent.objects.bulk_create, thread_sensitive=True)(batch)
            _send_event_signals(run, batch)
            batch.clear()
    if batch:
        await sync_to_async(AgentEvent.objects.bulk_create, thread_sensitive=True)(batch)
        _send_event_signals(run, batch)


def _serialize_event(event_serializer: Any, event: StreamEvent) -> dict[str, Any] | None:
    try:
        return event_serializer.serialize(event)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to serialize stream event", extra={"event_type": type(event).__name__})
    return None


def _event_type(event: StreamEvent) -> str:
    if isinstance(event, RunItemStreamEvent):
        return event.name
    return event.type


def _next_event_sequence(run: AgentRun) -> int:
    last_sequence = (
        AgentEvent.objects.filter(run=run)
        .aggregate(max_sequence=Max("sequence"))
        .get("max_sequence")
    )
    return (last_sequence or 0) + 1


def _send_event_signals(run: AgentRun, events: list[AgentEvent]) -> None:
    for event in events:
        agent_run_event.send_robust(
            sender=AgentEvent,
            run=run,
            event=event,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=event.payload,
        )


def recover_stuck_runs(mode: str) -> int:
    if mode not in {"fail", "requeue"}:
        return 0
    with transaction.atomic():
        _lock_guard()
        queryset = AgentRun.objects.filter(status=AgentRun.Status.RUNNING)
        if mode == "fail":
            updated = queryset.update(
                status=AgentRun.Status.FAILED,
                error="Server restart",
                finished_at=timezone.now(),
                task_id="",
                updated_at=timezone.now(),
            )
        else:
            updated = queryset.update(
                status=AgentRun.Status.PENDING,
                error="",
                started_at=None,
                finished_at=None,
                task_id="",
                updated_at=timezone.now(),
            )
    if mode == "requeue" and updated:
        dispatch_pending_runs()
    return updated


def maybe_recover_stuck_runs() -> None:
    global _startup_recovery_done
    global _startup_recovery_in_progress

    if _startup_recovery_done or _startup_recovery_in_progress:
        return
    with _startup_recovery_lock:
        if _startup_recovery_done or _startup_recovery_in_progress:
            return
        mode = get_settings().startup_recovery
        if mode == "ignore":
            _startup_recovery_done = True
            return
        _startup_recovery_in_progress = True
        try:
            recover_stuck_runs(mode)
        except (OperationalError, ProgrammingError):
            logger.debug("Skipping startup recovery; database not ready.")
            return
        finally:
            _startup_recovery_in_progress = False
        _startup_recovery_done = True
