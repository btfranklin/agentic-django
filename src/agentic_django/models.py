from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AgentSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=255)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_sessions",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("owner", "session_key")
        indexes = [
            models.Index(fields=["owner", "session_key"], name="agent_sess_owner_key_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.session_key} ({self.owner_id})"


class AgentSessionItem(models.Model):
    session = models.ForeignKey(
        AgentSession,
        on_delete=models.CASCADE,
        related_name="items",
    )
    sequence = models.PositiveBigIntegerField()
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("session", "sequence")
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["session", "sequence"], name="agent_sess_item_seq_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.session_id}:{self.sequence}"


class AgentRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        AgentSession,
        on_delete=models.CASCADE,
        related_name="runs",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_runs",
    )
    agent_key = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    input_payload = models.JSONField()
    final_output = models.JSONField(null=True, blank=True)
    raw_responses = models.JSONField(null=True, blank=True)
    last_response_id = models.CharField(max_length=200, blank=True, default="")
    error = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    task_id = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "status"], name="agent_run_owner_status_idx"),
            models.Index(fields=["status", "created_at"], name="agent_run_status_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.agent_key}:{self.status}"

    def mark_running(self) -> None:
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=["status", "started_at", "updated_at"])

    def mark_completed(self) -> None:
        self.status = self.Status.COMPLETED
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.status = self.Status.FAILED
        self.error = error
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "error", "finished_at", "updated_at"])


class AgentEvent(models.Model):
    run = models.ForeignKey(
        AgentRun,
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence = models.PositiveBigIntegerField()
    event_type = models.CharField(max_length=64)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("run", "sequence")
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.sequence}"


class AgentRunLock(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.key
