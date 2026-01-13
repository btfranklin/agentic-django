from __future__ import annotations

import json
from typing import Any

from asgiref.sync import async_to_sync
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from agentic_django.conf import get_settings, parse_rate_limit
from agentic_django.models import AgentEvent, AgentRun, AgentSession
from agentic_django.registry import get_agent_registry
from agentic_django.services import enqueue_agent_run
from agentic_django.signals import agent_session_created
from agentic_django.sessions import get_session


class AgentRunCreateView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest) -> HttpResponse:
        limit_error = _enforce_request_limits(request)
        if limit_error is not None:
            return limit_error
        try:
            payload = _parse_payload(request)
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        session_key = payload.get("session_key")
        if not session_key:
            return JsonResponse({"error": "session_key is required"}, status=400)

        input_payload = _parse_json_value(payload.get("input"))
        if input_payload in (None, ""):
            return JsonResponse({"error": "input is required"}, status=400)
        if not isinstance(input_payload, (str, list)):
            return JsonResponse({"error": "input must be a string or list"}, status=400)
        input_limit_error = _enforce_input_limits(input_payload)
        if input_limit_error is not None:
            return input_limit_error

        settings_config = get_settings()
        agent_key = payload.get("agent_key") or settings_config.default_agent_key
        registry = get_agent_registry()
        if agent_key not in registry:
            return JsonResponse({"error": "Unknown agent_key"}, status=400)

        session_key_value = str(session_key)
        # Initialize the configured session backend before creating the run.
        get_session(session_key_value, request.user)
        session, created = AgentSession.objects.get_or_create(
            session_key=session_key_value,
            owner=request.user,
        )
        if created:
            agent_session_created.send(sender=AgentSession, session=session)

        metadata: dict[str, Any] = {}
        config_payload = _parse_json_value(payload.get("config"))
        if isinstance(config_payload, dict):
            metadata["run_options"] = config_payload
        context_payload = _parse_json_value(payload.get("context"))
        if context_payload is not None:
            metadata["context"] = context_payload

        run = AgentRun.objects.create(
            session=session,
            owner=request.user,
            agent_key=agent_key,
            status=AgentRun.Status.PENDING,
            input_payload=input_payload,
            metadata=metadata,
            task_id="",
        )
        enqueue_agent_run(str(run.id))

        if _is_htmx(request):
            return render(
                request,
                "agentic_django/partials/run_fragment.html",
                {"run": run},
            )
        return JsonResponse({"run_id": str(run.id), "status": run.status})


class AgentRunDetailView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, run_id: str) -> JsonResponse:
        run = get_object_or_404(AgentRun, id=run_id, owner=request.user)
        payload = {
            "run_id": str(run.id),
            "status": run.status,
            "final_output": run.final_output,
            "error": run.error,
            "started_at": _format_time(run.started_at),
            "finished_at": _format_time(run.finished_at),
        }
        return JsonResponse(payload)


class AgentRunFragmentView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, run_id: str) -> HttpResponse:
        run = get_object_or_404(AgentRun, id=run_id, owner=request.user)
        return render(request, "agentic_django/partials/run_fragment.html", {"run": run})


class AgentRunEventsView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, run_id: str) -> JsonResponse:
        if not get_settings().enable_events:
            return JsonResponse({"error": "events disabled"}, status=404)

        run = get_object_or_404(AgentRun, id=run_id, owner=request.user)
        after_param = request.GET.get("after")
        limit_param = request.GET.get("limit")
        try:
            after = int(after_param) if after_param else None
        except ValueError:
            return JsonResponse({"error": "after must be an integer"}, status=400)
        try:
            limit = int(limit_param) if limit_param else None
        except ValueError:
            return JsonResponse({"error": "limit must be an integer"}, status=400)

        events = AgentEvent.objects.filter(run=run).order_by("sequence")
        if after is not None:
            events = events.filter(sequence__gt=after)
        if limit is not None:
            events = events[:limit]

        payload = [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": _format_time(event.created_at),
            }
            for event in events
        ]
        return JsonResponse({"run_id": str(run.id), "events": payload})


class AgentSessionItemsView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest, session_key: str) -> JsonResponse:
        session = get_object_or_404(
            AgentSession,
            session_key=session_key,
            owner=request.user,
        )
        backend_session = get_session(session.session_key, request.user)
        limit_param = request.GET.get("limit")
        try:
            limit = int(limit_param) if limit_param else None
        except ValueError:
            return JsonResponse({"error": "limit must be an integer"}, status=400)
        items = async_to_sync(backend_session.get_items)(limit)
        if _is_htmx(request):
            html_items = [{"payload": item} for item in items]
            return render(
                request,
                "agentic_django/partials/conversation.html",
                {"session": session, "items": html_items},
            )
        return JsonResponse({"session_key": session_key, "items": items})


def _parse_payload(request: HttpRequest) -> dict[str, Any]:
    if request.content_type and "application/json" in request.content_type:
        if not request.body:
            return {}
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON payload") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        return payload
    return request.POST.dict()


def _parse_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _format_time(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _enforce_request_limits(request: HttpRequest) -> JsonResponse | None:
    settings_config = get_settings()
    max_bytes = settings_config.max_input_bytes
    if max_bytes is not None:
        body = request.body
        if body and len(body) > max_bytes:
            return JsonResponse({"error": "payload too large"}, status=413)
    rate_limit = parse_rate_limit(settings_config.rate_limit)
    if rate_limit is None:
        return None
    max_calls, period_seconds = rate_limit
    user_id = getattr(request.user, "id", None)
    if user_id is None:
        return None
    cache_key = f"agentic_django:rate:{user_id}"
    current = cache.get(cache_key)
    if current is None:
        cache.set(cache_key, 1, timeout=period_seconds)
        return None
    if current >= max_calls:
        return JsonResponse({"error": "rate limit exceeded"}, status=429)
    try:
        cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, current + 1, timeout=period_seconds)
    return None


def _enforce_input_limits(input_payload: Any) -> JsonResponse | None:
    settings_config = get_settings()
    max_items = settings_config.max_input_items
    if max_items is None:
        return None
    if isinstance(input_payload, list) and len(input_payload) > max_items:
        return JsonResponse({"error": "too many input items"}, status=413)
    return None
