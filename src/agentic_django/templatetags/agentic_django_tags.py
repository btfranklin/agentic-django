from __future__ import annotations

import json
from typing import Any

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from agentic_django.async_bridge import run_async
from agentic_django.models import AgentSession
from agentic_django.serializers import _to_jsonable
from agentic_django.sessions import get_session

register = template.Library()


@register.inclusion_tag("agentic_django/partials/run_fragment.html")
def agent_run_fragment(run: Any) -> dict[str, Any]:
    return {"run": run}


@register.inclusion_tag("agentic_django/partials/conversation.html")
def agent_conversation(session: AgentSession) -> dict[str, Any]:
    backend = get_session(session.session_key, session.owner)
    items = run_async(backend.get_items)
    return {"session": session, "items": [{"payload": item} for item in items]}


@register.filter
def pretty_json(value: Any) -> str:
    payload = json.dumps(
        _to_jsonable(value),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return mark_safe(escape(payload))
