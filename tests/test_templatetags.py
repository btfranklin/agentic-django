from __future__ import annotations

from typing import Any

import pytest
from django.template import Context, Template


def test_pretty_json_formats_and_escapes_template_values() -> None:
    template = Template(
        "{% load agentic_django_tags %}{{ value|pretty_json }}"
    )

    rendered = template.render(Context({"value": {"html": "<b>hello</b>"}}))

    assert rendered == '{\n  &quot;html&quot;: &quot;&lt;b&gt;hello&lt;/b&gt;&quot;\n}'


@pytest.mark.django_db()
def test_conversation_tag_uses_configured_backend(
    user: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.test import override_settings
    from agentic_django.models import AgentSession
    from tests.support import RecordingSession

    session = AgentSession.objects.create(owner=user, session_key='external')
    session.items.create(sequence=1, payload={'role': 'user', 'content': 'stale'})
    calls = []

    def get_or_create(cls: Any, session_key: str, owner: Any) -> RecordingSession:
        calls.append((session_key, owner.pk))
        return cls(session_id=session_key)

    async def get_items(
        self: RecordingSession, limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return [{'role': 'assistant', 'content': 'external history'}]

    monkeypatch.setattr(RecordingSession, 'get_or_create', classmethod(get_or_create))
    monkeypatch.setattr(RecordingSession, 'get_items', get_items)
    with override_settings(
        AGENTIC_DJANGO_SESSION_BACKEND='tests.support.RecordingSession',
    ):
        rendered = Template(
            '{% load agentic_django_tags %}{% agent_conversation session %}'
        ).render(Context({'session': session}))

    assert 'external history' in rendered
    assert 'stale' not in rendered
    assert calls == [('external', user.pk)]
