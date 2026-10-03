from __future__ import annotations

import django
import sys
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

    from django.contrib.admin.sites import AdminSite
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory, override_settings
    from unittest.mock import patch

    from agentic_django.admin import AgentRunAdmin, AgentSessionAdmin
    from agentic_django.models import AgentRun, AgentSession
    from agentic_django.views import _enforce_request_limits

    request = RequestFactory().get("/")
    for model, admin_class in (
        (AgentRun, AgentRunAdmin), (AgentSession, AgentSessionAdmin),
    ):
        model_admin = admin_class(model, AdminSite())
        fields = model_admin.get_search_fields(request)
        lookup = "owner__account__key" if relational else "owner__email"
        model_admin.get_search_results(request, model.objects.all(), "needle")
        assert fields.count(lookup) == 1, fields
        assert "owner__username" not in fields, fields

    if relational:
        return

    owner = get_user_model()(account_key="employee", email="employee@example.com")
    assert not hasattr(owner, "id")
    request = RequestFactory().post("/runs/")
    request.user = owner
    with override_settings(AGENTIC_DJANGO_RATE_LIMIT="1/m"):
        with patch("agentic_django.views.admit_request", return_value=False) as admit:
            response = _enforce_request_limits(request)
    assert response is not None and response.status_code == 429
    admit.assert_called_once_with(owner, 1, 60)


if __name__ == "__main__":
    main()
