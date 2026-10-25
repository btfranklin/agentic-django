from __future__ import annotations

import asyncio
import atexit
import os
from collections.abc import Awaitable, Callable
from contextvars import Context, copy_context
from threading import Event, Lock, Thread, current_thread
from types import TracebackType
from typing import ParamSpec, TypeVar, cast

from asgiref.current_thread_executor import CurrentThreadExecutor
from asgiref.sync import SyncToAsync, async_to_sync

P = ParamSpec("P")
T = TypeVar("T")


class _CallerThreadCall(SyncToAsync[P, T]):
    """Keep the host's ASGI loop and task state after a bridge call."""

    def thread_handler(
        self,
        loop: asyncio.AbstractEventLoop,
        exc_info: tuple[
            type[BaseException] | None,
            BaseException | None,
            TracebackType | None,
        ],
        task_context: list[asyncio.Task[object]],
        func: Callable[P, T],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        # The base handler sets the caller's state to the bridge loop.
        previous_state: dict[str, object] = self.threadlocal.__dict__.copy()
        try:
            # asgiref leaves this internal method untyped. Its result is the
            # result of func(*args, **kwargs), whose types are preserved here.
            result = super().thread_handler(  # type: ignore[no-untyped-call]
                loop,
                exc_info,
                task_context,
                func,
                *args,
                **kwargs,
            )
            return cast(T, result)
        finally:
            self.threadlocal.__dict__.clear()
            self.threadlocal.__dict__.update(previous_state)


async def _invoke(function: Callable[[], Awaitable[T]]) -> T:
    return await function()


async def _call_on_loop(
    function: Callable[[], Awaitable[T]],
    executor: CurrentThreadExecutor,
    context: Context,
) -> T:
    caller = async_to_sync(_invoke)

    def invoke_on_caller() -> T:
        return context.run(caller, function)

    # asgiref annotates executor as ThreadPoolExecutor, but only uses submit().
    # CurrentThreadExecutor implements that interface and preserves DB locality.
    return await _CallerThreadCall(
        invoke_on_caller,
        thread_sensitive=False,
        executor=executor,  # type: ignore[arg-type]
    )()


class _AsyncBridge:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ready = Event()
        self.error: BaseException | None = None
        self.thread = Thread(
            target=self._serve,
            name="agentic-django-async",
            daemon=True,
        )
        self.thread.start()
        self.ready.wait()
        loop = self._started_loop()
        if self.error is not None or loop is None or not loop.is_running():
            raise RuntimeError("Could not start the async bridge") from self.error

    def _started_loop(self) -> asyncio.AbstractEventLoop | None:
        # The loop thread sets this field before it signals ready.
        return self.loop

    def _serve(self) -> None:
        try:
            with asyncio.Runner() as runner:
                self.loop = runner.get_loop()
                self.loop.call_soon(self.ready.set)
                self.loop.run_forever()
        except BaseException as exc:
            self.error = exc
        finally:
            self.ready.set()

    def close(self) -> None:
        if self.loop is not None and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread is not current_thread():
            self.thread.join(timeout=5)


_startup_lock = Lock()
_bridge: _AsyncBridge | None = None


def run_async(
    function: Callable[P, Awaitable[T]],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Run async work on the shared loop and keep sync work on its caller."""
    global _bridge
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "Call run_async from a sync thread; await from an async thread"
        )
    with _startup_lock:
        if _bridge is None or not _bridge.thread.is_alive():
            _bridge = _AsyncBridge()
        loop = _bridge.loop
    if loop is None:
        raise RuntimeError("The async bridge is not ready")
    executor = CurrentThreadExecutor(None)
    context = copy_context()

    async def invoke() -> T:
        return await function(*args, **kwargs)

    future = asyncio.run_coroutine_threadsafe(
        _call_on_loop(invoke, executor, context),
        loop,
    )
    try:
        executor.run_until_future(future)
        return future.result()
    finally:
        # The inner async_to_sync call has restored these values on this thread.
        for variable, value in context.items():
            variable.set(value)


def _close_async_bridge() -> None:
    global _bridge
    with _startup_lock:
        if _bridge is not None:
            _bridge.close()
            _bridge = None


def _reset_after_fork() -> None:
    global _startup_lock, _bridge
    # A fork does not preserve the loop thread or a usable startup lock.
    _startup_lock = Lock()
    _bridge = None


atexit.register(_close_async_bridge)
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)
