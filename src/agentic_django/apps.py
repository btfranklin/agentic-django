from __future__ import annotations

from django.apps import AppConfig


class AgenticDjangoConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agentic_django"
    verbose_name = "Agentic Django"

    def ready(self) -> None:
        from .conf import validate_settings

        validate_settings()
