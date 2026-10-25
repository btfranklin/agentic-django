from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser

from agents import SessionABC
from agents.items import TResponseInputItem
from agents.memory.session import Session
from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from agentic_django.conf import get_settings
from agentic_django.models import AgentSession, AgentSessionItem
from agentic_django.serializers import ItemSerializer
from agentic_django.signals import agent_session_created
from agentic_django.types import input_items, json_value


class DatabaseSession(SessionABC):
    def __init__(self, session: AgentSession) -> None:
        self._session = session
        self.session_id = str(session.id)

    @classmethod
    def get_or_create(
        cls, session_key: str, owner: AbstractBaseUser
    ) -> "DatabaseSession":
        session, created = AgentSession.objects.get_or_create(
            session_key=session_key,
            owner_id=owner.pk,
        )
        if created:
            agent_session_created.send(sender=AgentSession, session=session)
        return cls(session)

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        return await sync_to_async(self._get_items, thread_sensitive=True)(limit)

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        await sync_to_async(self._add_items, thread_sensitive=True)(items)

    async def pop_item(self) -> TResponseInputItem | None:
        return await sync_to_async(self._pop_item, thread_sensitive=True)()

    async def clear_session(self) -> None:
        await sync_to_async(self._clear_session, thread_sensitive=True)()

    def _get_items(self, limit: int | None) -> list[TResponseInputItem]:
        serializer = _get_item_serializer()
        queryset = AgentSessionItem.objects.filter(session=self._session).order_by(
            "sequence"
        )
        if limit is not None:
            queryset = queryset.order_by("-sequence")[:limit]
            items = list(reversed(list(queryset)))
        else:
            items = list(queryset)
        return input_items([serializer.deserialize(item.payload) for item in items])

    def _add_items(self, items: list[TResponseInputItem]) -> None:
        if not items:
            return
        serializer = _get_item_serializer()
        normalized = [json_value(serializer.serialize(item)) for item in items]
        with transaction.atomic():
            # Write first so SQLite also locks before reading history.
            AgentSession.objects.filter(id=self._session.id).update(
                updated_at=timezone.now(),
            )
            session = AgentSession.objects.get(id=self._session.id)
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

    def _pop_item(self) -> TResponseInputItem | None:
        serializer = _get_item_serializer()
        with transaction.atomic():
            # Write first so SQLite also locks before reading history.
            AgentSession.objects.filter(id=self._session.id).update(
                updated_at=timezone.now(),
            )
            session = AgentSession.objects.get(id=self._session.id)
            last_item = (
                AgentSessionItem.objects.filter(session=session)
                .order_by("-sequence")
                .first()
            )
            if last_item is None:
                return None
            payload = last_item.payload
            last_item.delete()
            return input_items([serializer.deserialize(payload)])[0]

    def _clear_session(self) -> None:
        with transaction.atomic():
            # Write first so SQLite also locks before reading history.
            AgentSession.objects.filter(id=self._session.id).update(
                updated_at=timezone.now(),
            )
            session = AgentSession.objects.get(id=self._session.id)
            AgentSessionItem.objects.filter(session=session).delete()


def get_session(session_key: str, owner: AbstractBaseUser) -> Session:
    backend_path = get_settings().session_backend
    backend_cls = import_string(backend_path)
    get_or_create = getattr(backend_cls, "get_or_create", None)
    if not callable(get_or_create):
        raise ValueError(
            "Session backend must define get_or_create(session_key, owner)"
        )
    session: object = get_or_create(session_key, owner)
    if not isinstance(session, Session):
        raise ValueError("Session backend must return an SDK Session")
    return session


def _get_item_serializer() -> ItemSerializer:
    serializer_path = get_settings().session_item_serializer
    serializer_cls = import_string(serializer_path)
    serializer: object = serializer_cls()
    if not isinstance(serializer, ItemSerializer):
        raise ValueError(
            "Session item serializer must define serialize and deserialize"
        )
    return serializer
