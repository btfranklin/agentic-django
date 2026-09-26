from __future__ import annotations

from typing import Any

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.test import RequestFactory

from agentic_django.admin import AgentRunAdmin
from agentic_django.models import AgentRun, AgentSession


@pytest.mark.django_db()
@pytest.mark.parametrize(
    ('permission', 'action', 'allowed'),
    [
        ('view', 'purge_runs', False),
        ('view', 'requeue_runs', False),
        ('change', 'purge_runs', False),
        ('delete', 'requeue_runs', False),
        ('change', 'requeue_runs', True),
        ('delete', 'purge_runs', True),
    ],
)
def test_run_actions_enforce_model_permissions(
    user: Any, monkeypatch: pytest.MonkeyPatch,
    permission: str, action: str, allowed: bool,
) -> None:
    user.is_staff = True
    user.save()
    user.user_permissions.add(Permission.objects.get(codename=f'{permission}_agentrun'))
    session = AgentSession.objects.create(owner=user, session_key='admin')
    run = AgentRun.objects.create(
        owner=user, session=session, agent_key='default', input_payload='hi',
        status=AgentRun.Status.COMPLETED,
    )
    request = RequestFactory().post('/', {
        'action': action, '_selected_action': str(run.pk),
    })
    request.user = user
    model_admin = AgentRunAdmin(AgentRun, AdminSite())
    monkeypatch.setattr(model_admin, 'message_user', lambda *args, **kwargs: None)
    enqueued: list[str] = []
    monkeypatch.setattr('agentic_django.admin.enqueue_agent_run', enqueued.append)

    assert (action in model_admin.get_actions(request)) is allowed
    model_admin.response_action(request, AgentRun.objects.all())

    if allowed and action == 'purge_runs':
        assert not AgentRun.objects.filter(pk=run.pk).exists()
    else:
        run.refresh_from_db()
        assert run.status == (
            AgentRun.Status.PENDING if allowed else AgentRun.Status.COMPLETED
        )
    assert enqueued == ([str(run.pk)] if allowed and action == 'requeue_runs' else [])
