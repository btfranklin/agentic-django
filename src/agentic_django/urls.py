from __future__ import annotations

from django.urls import path

from agentic_django import views

app_name = "agents"

urlpatterns = [
    path("runs/", views.AgentRunCreateView.as_view(), name="run-create"),
    path("runs/<uuid:run_id>/", views.AgentRunDetailView.as_view(), name="run-detail"),
    path(
        "runs/<uuid:run_id>/fragment/",
        views.AgentRunFragmentView.as_view(),
        name="run-fragment",
    ),
    path(
        "runs/<uuid:run_id>/events/",
        views.AgentRunEventsView.as_view(),
        name="run-events",
    ),
    path(
        "sessions/<slug:session_key>/items/",
        views.AgentSessionItemsView.as_view(),
        name="session-items",
    ),
]
