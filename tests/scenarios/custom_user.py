from __future__ import annotations

import sys

import django
from django.conf import settings

from tests import settings as base_settings


def main() -> None:
    relational = len(sys.argv) > 1 and sys.argv[1] == "relation"
    configured = {
        key: value for key, value in vars(base_settings).items() if key.isupper()
    }
    configured["AUTH_USER_MODEL"] = (
        "custom_user_app.RelationUser" if relational else "custom_user_app.User"
    )
    configured["INSTALLED_APPS"] = [
        *configured["INSTALLED_APPS"], "tests.scenarios.custom_user_app",
    ]
    settings.configure(**configured)
    django.setup()

    from unittest.mock import patch

    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory, override_settings

    from agentic_django.admin import AgentRunAdmin, AgentSessionAdmin
    from agentic_django.models import AgentRun, AgentSession
    from agentic_django.views import _enforce_request_limits
    from tests.scenarios.custom_user_app.models import User as CustomUser

    request = RequestFactory().get("/")
    lookup = "owner__account__key" if relational else "owner__email"
    run_admin = AgentRunAdmin(AgentRun, AdminSite())
    run_fields = run_admin.get_search_fields(request)
    run_admin.get_search_results(request, AgentRun.objects.all(), "needle")
    assert run_fields.count(lookup) == 1, run_fields
    assert "owner__username" not in run_fields, run_fields
    session_admin = AgentSessionAdmin(AgentSession, AdminSite())
    session_fields = session_admin.get_search_fields(request)
    session_admin.get_search_results(request, AgentSession.objects.all(), "needle")
    assert session_fields.count(lookup) == 1, session_fields
    assert "owner__username" not in session_fields, session_fields

    if relational:
        return

    owner = CustomUser(account_key="employee", email="employee@example.com")
    assert not hasattr(owner, "id")
    request = RequestFactory().post("/runs/")
    # The Django plugin uses the default test user for request.user.
    request.user = owner  # type: ignore[assignment]
    with override_settings(AGENTIC_DJANGO_RATE_LIMIT="1/m"):
        with patch("agentic_django.views.admit_request", return_value=False) as admit:
            response = _enforce_request_limits(request)
    assert response is not None and response.status_code == 429
    admit.assert_called_once_with(owner, 1, 60)


if __name__ == "__main__":
    main()
