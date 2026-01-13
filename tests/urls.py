from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("", include(("agentic_django.urls", "agents"), namespace="agents")),
]
