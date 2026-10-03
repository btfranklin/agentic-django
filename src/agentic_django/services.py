from __future__ import annotations

import logging
import traceback
import uuid
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from threading import local
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings as django_settings
from django.db import connection, transaction
from django.db.models import Max, Q
from django.utils import timezone
from django.utils.module_loading import import_string

from agents import Runner
from agents.stream_events import RunItemStreamEvent, StreamEvent

from agentic_django.async_bridge import run_async
from agentic_django.conf import get_concurrency_limit, get_settings
from agentic_django.models import AgentEvent, AgentRun, AgentRunLock, AgentSession
from agentic_django.registry import get_agent
from agentic_django.serializers import JsonSerializer
from agentic_django.sessions import get_session
from agentic_django.signals import (
    agent_run_completed,
    agent_run_event,
    agent_run_failed,
    agent_run_started,
    agent_session_created,
)

logger = logging.getLogger(__name__)
_submission_state = local()


def submit_agent_run(
    *,
    owner: Any,
    session_key: str,
    agent_key: str,
    input_payload: str | list[Any],
    metadata: dict[str, Any] | None = None,
) -> AgentRun:
    """Create a run from validated input and enqueue it after commit."""
    with transaction.atomic():
        # Lock session reuse before cleanup can check its age and contents.
        AgentSession.objects.filter(
            session_key=session_key, owner=owner,
        ).update(updated_at=timezone.now())
        # Initialize the configured backend before creating the local run.
        get_session(session_key, owner)
        session, created = AgentSession.objects.get_or_create(
            session_key=session_key, owner=owner,
        )
        if created:
            agent_session_created.send(sender=AgentSession, session=session)
        run = AgentRun.objects.create(
            session=session,
            owner=owner,
            agent_key=agent_key,
            input_payload=input_payload,
            metadata=metadata if metadata is not None else {},
        )
        enqueue_agent_run(str(run.id))
    return run


def enqueue_agent_run(run_id: str) -> None:
    def _enqueue() -> None:
        token = f"queued:{uuid.uuid4()}"
        reserved = AgentRun.objects.filter(
            id=run_id, status=AgentRun.Status.PENDING, task_id=""
        ).update(task_id=token, updated_at=timezone.now())
        if reserved:
            _enqueue_reserved_runs([(run_id, token)])

    transaction.on_commit(_enqueue)


def _enqueue_reserved_runs(reservations: list[tuple[str, str]]) -> None:
    from agentic_django.tasks import run_agent_task

    pending = getattr(_submission_state, "pending", None)
    if pending is not None:
        pending.extend(reservations)
        return
    pending = deque(reservations)
    _submission_state.pending = pending
    try:
        while pending:
            run_id, token = pending.popleft()
            try:
                task_result = run_agent_task.enqueue(run_id)
            except Exception:
                # Release only reservations that this callback still owns.
                pending.appendleft((run_id, token))
                for pending_id, pending_token in pending:
                    AgentRun.objects.filter(
                        id=pending_id, task_id=pending_token,
                    ).update(task_id="", updated_at=timezone.now())
                raise
            AgentRun.objects.filter(id=run_id, task_id=token).update(
                task_id=task_result.id, updated_at=timezone.now()
            )
    finally:
        _submission_state.pending = None


def dispatch_pending_runs() -> int:
    limit = get_concurrency_limit()
    enqueued: list[tuple[str, str]] = []
    with _dispatch_lock():
        running_count = AgentRun.objects.filter(status=AgentRun.Status.RUNNING).count()
        available = max(0, limit - running_count)
        if available == 0:
            return 0
        pending_runs = AgentRun.objects.filter(
            status=AgentRun.Status.PENDING,
            task_id="",
        ).order_by("created_at", "id")
        if connection.features.has_select_for_update_skip_locked:
            pending_runs = pending_runs.select_for_update(skip_locked=True)
        else:
            pending_runs = pending_runs.select_for_update()
        active_sessions = set(
            AgentRun.objects.filter(status=AgentRun.Status.RUNNING)
            .values_list("session_id", flat=True)
        )
        while len(enqueued) < available:
            # Fetch one eligible row per slot without loading the full backlog.
            run = pending_runs.exclude(session_id__in=active_sessions).first()
            if run is None:
                break
            active_sessions.add(run.session_id)
            token = f"queued:{uuid.uuid4()}"
            run.task_id = token
            run.save(update_fields=["task_id", "updated_at"])
            enqueued.append((str(run.id), token))

        if not enqueued:
            return 0

        transaction.on_commit(lambda: _enqueue_reserved_runs(enqueued))
        return len(enqueued)


def execute_run(run_id: str) -> None:
    run = AgentRun.objects.select_related("session", "owner").get(id=run_id)
    if run.status != AgentRun.Status.PENDING:
        return
    if not _reserve_run_slot(run):
        AgentRun.objects.filter(id=run_id, status=AgentRun.Status.PENDING).update(
            task_id="", updated_at=timezone.now()
        )
        _dispatch_after_run(run)
        return

    result = None
    try:
        agent_run_started.send_robust(sender=AgentRun, run=run)
        serializer = _get_serializer()
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
            result = run_async(
                Runner.run,
                agent,
                run.input_payload,
                session=session,
                context=context,
                **run_options,
            )
        if result.interruptions:
            raise ValueError("Agent runs that require tool approval are not supported.")
        run.final_output = serializer.serialize(result.final_output)
        run.raw_responses = serializer.serialize(result.raw_responses)
        run.last_response_id = result.last_response_id or ""
        run.error = ""
        run.task_id = ""
        run.status = AgentRun.Status.COMPLETED
        run.finished_at = timezone.now()
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
        agent_run_completed.send_robust(sender=AgentRun, run=run, result=result)
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
        agent_run_failed.send_robust(sender=AgentRun, run=run, exception=exc)
        raise
    finally:
        try:
            if result is not None:
                result.release_agents()
        finally:
            _dispatch_after_run(run)


def _dispatch_after_run(run: AgentRun) -> None:
    try:
        dispatch_pending_runs()
    except Exception:
        logger.exception(
            "Failed to dispatch pending agent runs", extra={"run_id": str(run.id)},
        )


def _reserve_run_slot(run: AgentRun) -> bool:
    limit = get_concurrency_limit()
    with _dispatch_lock():
        running_count = AgentRun.objects.filter(status=AgentRun.Status.RUNNING).count()
        if running_count >= limit:
            return False
        if AgentRun.objects.filter(
            session_id=run.session_id, status=AgentRun.Status.RUNNING
        ).exists():
            return False
        run.refresh_from_db(fields=["status"])
        if run.status != AgentRun.Status.PENDING:
            return False
        run.status = AgentRun.Status.RUNNING
        run.started_at = timezone.now()
        run.save(update_fields=["status", "started_at", "updated_at"])
    return True


@contextmanager
def _dispatch_lock() -> Iterator[None]:
    AgentRunLock.objects.get_or_create(key="global")
    with transaction.atomic():
        # Write before reading run state to acquire the SQLite write lock too.
        AgentRunLock.objects.filter(key="global").update(updated_at=timezone.now())
        yield


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


def _format_error(exc: Exception) -> str:
    if django_settings.DEBUG:
        return "".join(traceback.format_exception(exc)).strip()
    return "The agent run failed. Contact support with the run ID."


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

    return run_async(_consume)


async def _consume_stream_events(
    *,
    run: AgentRun,
    result: Any,
    event_serializer: Any,
    starting_sequence: int,
) -> None:
    sequence = starting_sequence
    events = result.stream_events()
    try:
        async for event in events:
            payload = _serialize_event(event_serializer, event)
            if payload is None:
                continue
            stored_event = AgentEvent(
                run=run,
                sequence=sequence,
                event_type=_event_type(event),
                payload=payload,
            )
            await sync_to_async(_persist_event, thread_sensitive=True)(
                run, stored_event,
            )
            sequence += 1
        task = result.run_loop_task
        if task is not None and task.cancelled():
            raise RuntimeError("The agent stream was cancelled before completion.")
    except BaseException:
        result.cancel()
        try:
            await events.aclose()
        except BaseException:
            logger.exception(
                "Failed to close agent event stream", extra={"run_id": str(run.id)},
            )
        finally:
            result.release_agents()
        raise


def _persist_event(run: AgentRun, event: AgentEvent) -> None:
    event.save()
    agent_run_event.send_robust(
        sender=AgentEvent,
        run=run,
        event=event,
        sequence=event.sequence,
        event_type=event.event_type,
        payload=event.payload,
    )


def _serialize_event(
    event_serializer: Any,
    event: StreamEvent,
) -> dict[str, Any] | None:
    try:
        return event_serializer.serialize(event)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to serialize stream event",
            extra={"event_type": type(event).__name__},
        )
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


def recover_stuck_runs(mode: str, *, include_pending: bool = False) -> int:
    if mode not in {"fail", "requeue"}:
        return 0
    with _dispatch_lock():
        affected = Q(status=AgentRun.Status.RUNNING)
        if include_pending:
            affected |= Q(status=AgentRun.Status.PENDING) & ~Q(task_id="")
        queryset = AgentRun.objects.filter(affected)
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
