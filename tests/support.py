from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar

from agents import SessionABC


def _build_agent() -> object:
    return object()


def get_agent_registry() -> dict[str, Callable[[], Any]]:
    return {"default": _build_agent}


class RecordingSession(SessionABC):
    called: ClassVar[bool] = False

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    @classmethod
    def get_or_create(cls, session_key: str, owner: Any) -> "RecordingSession":
        cls.called = True
        return cls(session_id=f"recording:{session_key}")

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        return []

    async def add_items(self, items: list[dict[str, Any]]) -> None:
        return None

    async def pop_item(self) -> dict[str, Any] | None:
        return None

    async def clear_session(self) -> None:
        return None
