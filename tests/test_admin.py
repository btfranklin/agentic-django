from __future__ import annotations

from typing import Any
import subprocess
import sys

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from agentic_django.admin import AgentRunAdmin, AgentSessionAdmin
from agentic_django.models import AgentRun, AgentSession


@pytest.mark.parametrize("identity", ["email", "relation"])
def test_admin_and_rate_limits_support_a_custom_user_model(identity: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.scenarios.custom_user", identity],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.django_db()
def test_admin_save_cannot_overwrite_a_worker_completion(
    user: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user.is_staff = True
    user.save()
    user.user_permissions.add(Permission.objects.get(codename="change_agentrun"))
    session = AgentSession.objects.create(owner=user, session_key="admin-save")
    run = AgentRun.objects.create(
        owner=user, session=session, agent_key="default", input_payload="hello",
        status=AgentRun.Status.RUNNING, task_id="worker-task",
    )
    request = RequestFactory().post("/", {"_save": "Save"})
    request.user = user
    request._dont_enforce_csrf_checks = True
    model_admin = AgentRunAdmin(AgentRun, AdminSite())
    finished_at = timezone.now()
    loaded = model_admin.get_object(request, str(run.pk))
    AgentRun.objects.filter(pk=run.pk).update(
        status=AgentRun.Status.COMPLETED, final_output="worker output",
        finished_at=finished_at, task_id="",
    )
    monkeypatch.setattr(model_admin, "get_object", lambda *a, **kw: loaded)
    monkeypatch.setattr(model_admin, "_create_formsets", lambda *a, **kw: ([], []))
    monkeypatch.setattr(model_admin, "log_change", lambda *a, **kw: None)
    monkeypatch.setattr(
        model_admin, "response_change", lambda *a, **kw: HttpResponse("saved"),
    )
    denied = False
    try:
        model_admin.changeform_view(request, str(run.pk))
    except PermissionDenied:
        denied = True
    run.refresh_from_db()
    assert run.status == AgentRun.Status.COMPLETED
    assert run.final_output == "worker output"
    assert run.finished_at == finished_at
    assert run.task_id == ""
    assert denied
    assert model_admin.has_view_permission(request, run)
    assert model_admin.has_change_permission(request)
    assert not model_admin.has_change_permission(request, run)
    assert "requeue_runs" in model_admin.get_actions(request)


@pytest.mark.django_db()
def test_admin_run_form_rejects_another_owners_session(user: Any) -> None:
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="other-owner")
    session = AgentSession.objects.create(session_key="private", owner=other)
    request = RequestFactory().get("/")
    request.user = user
    model_admin = AgentRunAdmin(AgentRun, AdminSite())
    form = model_admin.get_form(request)(data={
        "owner": user.pk, "session": session.pk, "agent_key": "default",
        "status": AgentRun.Status.PENDING, "input_payload": '"hello"',
        "metadata": "{}",
    })
    assert not form.is_valid()
    assert "session" in form.errors


@pytest.mark.django_db()
def test_admin_session_form_keeps_owner_with_runs(user: Any) -> None:
    from django.contrib.auth import get_user_model

    other = get_user_model().objects.create_user(username="other-owner")
    session = AgentSession.objects.create(session_key="private", owner=user)
    AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
    )
    request = RequestFactory().get("/")
    request.user = user
    model_admin = AgentSessionAdmin(AgentSession, AdminSite())
    form = model_admin.get_form(request, session)(data={
        "owner": other.pk, "session_key": session.session_key, "metadata": "{}",
    }, instance=session)
    assert form.is_valid(), form.errors
    form.save()
    session.refresh_from_db()
    assert session.owner == user


@pytest.mark.django_db()
def test_admin_preserves_existing_execution_identity_and_state(user: Any) -> None:
    session = AgentSession.objects.create(session_key="active", owner=user)
    other = AgentSession.objects.create(session_key="other", owner=user)
    run = AgentRun.objects.create(
        session=session, owner=user, agent_key="default", input_payload="hello",
        status=AgentRun.Status.RUNNING,
    )
    request = RequestFactory().get("/")
    request.user = user
    run_admin = AgentRunAdmin(AgentRun, AdminSite())
    run_form = run_admin.get_form(request, run)(data={
        "owner": user.pk, "session": other.pk, "agent_key": "default",
        "status": AgentRun.Status.COMPLETED, "input_payload": '"changed"',
        "metadata": "{}",
    }, instance=run)
    assert run_form.is_valid(), run_form.errors
    run_form.save()
    run.refresh_from_db()
    assert run.session_id == session.pk
    assert run.status == AgentRun.Status.RUNNING
    assert run.input_payload == "hello"
    assert not run_admin.has_add_permission(request)

    session_admin = AgentSessionAdmin(AgentSession, AdminSite())
    session_form = session_admin.get_form(request, session)(data={
        "owner": user.pk, "session_key": "changed-key", "metadata": "{}",
    }, instance=session)
    assert session_form.is_valid(), session_form.errors
    session_form.save()
    session.refresh_from_db()
    assert session.session_key == "active"


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
