from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from agents import SessionABC

from agentic_django.conf import get_settings
from agentic_django.models import AgentSession, AgentSessionItem
from agentic_django.signals import agent_session_created


class DatabaseSession(SessionABC):
    def __init__(self, session: AgentSession) -> None:
        self._session = session
        self.session_id = str(session.id)

    @classmethod
    def get_or_create(cls, session_key: str, owner: Any) -> "DatabaseSession":
        session, created = AgentSession.objects.get_or_create(
            session_key=session_key,
            owner=owner,
        )
        if created:
            agent_session_created.send(sender=AgentSession, session=session)
        return cls(session)

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        return await sync_to_async(self._get_items, thread_sensitive=True)(limit)

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        await sync_to_async(self._add_items, thread_sensitive=True)(items)

    async def pop_item(self) -> dict[str, Any] | None:
        return await sync_to_async(self._pop_item, thread_sensitive=True)()

    async def clear_session(self) -> None:
        await sync_to_async(self._clear_session, thread_sensitive=True)()

    def _get_items(self, limit: int | None) -> list[dict[str, Any]]:
        serializer = _get_item_serializer()
        queryset = AgentSessionItem.objects.filter(session=self._session).order_by("sequence")
        if limit is not None:
            queryset = queryset.order_by("-sequence")[:limit]
            items = list(reversed(list(queryset)))
        else:
            items = list(queryset)
        return [serializer.deserialize(item.payload) for item in items]

    def _add_items(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        serializer = _get_item_serializer()
        normalized = [serializer.serialize(item) for item in items]
        with transaction.atomic():
            session = AgentSession.objects.select_for_update().get(id=self._session.id)
            last_item = (
                AgentSessionItem.objects.filter(session=session)
                .order_by("-sequence")
                .first()
            )
            next_sequence = 1 if last_item is None else last_item.sequence + 1
            batch = []
            for offset, payload in enumerate(normalized):
                batch.append(
                    AgentSessionItem(
                        session=session,
                        sequence=next_sequence + offset,
                        payload=payload,
                    )
                )
            AgentSessionItem.objects.bulk_create(batch)
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])

    def _pop_item(self) -> dict[str, Any] | None:
        serializer = _get_item_serializer()
        with transaction.atomic():
            session = AgentSession.objects.select_for_update().get(id=self._session.id)
            last_item = (
                AgentSessionItem.objects.filter(session=session)
                .order_by("-sequence")
                .first()
            )
            if last_item is None:
                return None
            payload = last_item.payload
            last_item.delete()
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])
            return serializer.deserialize(payload)

    def _clear_session(self) -> None:
        with transaction.atomic():
            session = AgentSession.objects.select_for_update().get(id=self._session.id)
            AgentSessionItem.objects.filter(session=session).delete()
            session.updated_at = timezone.now()
            session.save(update_fields=["updated_at"])


def get_session(session_key: str, owner: Any) -> SessionABC:
    backend_path = get_settings().session_backend
    backend_cls = import_string(backend_path)
    get_or_create = getattr(backend_cls, "get_or_create", None)
    if not callable(get_or_create):
        raise ValueError("Session backend must define get_or_create(session_key, owner)")
    return get_or_create(session_key, owner)


def _get_item_serializer() -> Any:
    serializer_path = get_settings().session_item_serializer
    serializer_cls = import_string(serializer_path)
    return serializer_cls()
