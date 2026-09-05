from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("agentic_django", "0002_single_running_session"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AgentRequestLimit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True,
                        serialize=False, verbose_name="ID",
                    ),
                ),
                (
                    "window_started_at",
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ("count", models.PositiveBigIntegerField(default=0)),
                (
                    "owner",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agent_request_limit",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
