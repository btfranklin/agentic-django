from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from agents import Agent, SessionABC
from agents.items import TResponseInputItem


def _build_agent() -> Agent[object]:
    return Agent[object](name="test")


def get_agent_registry() -> dict[str, Callable[[], Agent[object]]]:
    return {"default": _build_agent}


class RecordingSession(SessionABC):
    called: ClassVar[bool] = False

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    @classmethod
    def get_or_create(cls, session_key: str, owner: object) -> "RecordingSession":
        cls.called = True
        return cls(session_id=f"recording:{session_key}")

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        return []

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        return None

    async def pop_item(self) -> TResponseInputItem | None:
        return None

    async def clear_session(self) -> None:
        return None
