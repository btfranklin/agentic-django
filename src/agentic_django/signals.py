from __future__ import annotations

from django.dispatch import Signal

agent_run_started = Signal()
agent_run_completed = Signal()
agent_run_failed = Signal()
agent_session_created = Signal()
agent_run_event = Signal()
