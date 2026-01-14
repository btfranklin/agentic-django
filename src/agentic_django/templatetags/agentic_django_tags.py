from __future__ import annotations

import json
from typing import Any

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

from agentic_django.models import AgentSession, AgentSessionItem
from agentic_django.serializers import _to_jsonable

register = template.Library()


@register.inclusion_tag("agentic_django/partials/run_fragment.html")
def agent_run_fragment(run: Any) -> dict[str, Any]:
    return {"run": run}


@register.inclusion_tag("agentic_django/partials/conversation.html")
def agent_conversation(session: AgentSession) -> dict[str, Any]:
    items = AgentSessionItem.objects.filter(session=session).order_by("sequence")
    return {"session": session, "items": items}


@register.filter
def pretty_json(value: Any) -> str:
    payload = json.dumps(
        _to_jsonable(value),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    )
    return mark_safe(escape(payload))
