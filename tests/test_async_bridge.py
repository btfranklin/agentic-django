from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier, Event, get_ident
from typing import Any

import pytest
from asgiref.sync import SyncToAsync, async_to_sync, sync_to_async
from asgiref.local import Local
from django.contrib.auth import get_user_model

from agentic_django.async_bridge import _close_async_bridge, run_async


@pytest.fixture(autouse=True)
def reset_bridge() -> Any:
    _close_async_bridge()
    yield
    _close_async_bridge()


def test_repeated_calls_use_one_live_loop_and_keep_sync_work_on_the_caller() -> None:
    caller_id = get_ident()

    async def inspect_call(value: str) -> tuple[asyncio.AbstractEventLoop, int, str]:
        sync_thread = await sync_to_async(get_ident, thread_sensitive=True)()
        return asyncio.get_running_loop(), sync_thread, value

    first_loop, first_thread, first_value = run_async(inspect_call, "first")
    second_loop, second_thread, second_value = run_async(inspect_call, value="second")

    assert first_loop is second_loop
    assert first_loop.is_running()
    assert not first_loop.is_closed()
    assert first_thread == second_thread == caller_id
    assert (first_value, second_value) == ("first", "second")


def test_concurrent_callers_share_the_loop_and_keep_their_own_sync_threads() -> None:
    worker_count = 4
    barrier = Barrier(worker_count)
    all_started: asyncio.Event | None = None
    started = 0

    async def inspect_call() -> tuple[asyncio.AbstractEventLoop, int]:
        nonlocal all_started, started
        if all_started is None:
            all_started = asyncio.Event()
        started += 1
        if started == worker_count:
            all_started.set()
        await asyncio.wait_for(all_started.wait(), timeout=5)
        sync_thread = await sync_to_async(get_ident, thread_sensitive=True)()
        return asyncio.get_running_loop(), sync_thread

    def worker() -> tuple[asyncio.AbstractEventLoop, int, int]:
        caller_id = get_ident()
        previous_state = SyncToAsync.threadlocal.__dict__.copy()
        barrier.wait(timeout=5)
        loop, sync_thread = run_async(inspect_call)
        assert SyncToAsync.threadlocal.__dict__ == previous_state
        return loop, sync_thread, caller_id

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(lambda _: worker(), range(worker_count)))

    assert len({id(loop) for loop, _, _ in results}) == 1
    assert len({caller for _, _, caller in results}) == worker_count
    assert all(sync_thread == caller for _, sync_thread, caller in results)


@pytest.mark.django_db()
def test_database_work_can_read_the_callers_uncommitted_transaction(user: Any) -> None:
    def read_user() -> str:
        return get_user_model().objects.get(pk=user.pk).username

    async def read() -> str:
        return await sync_to_async(read_user, thread_sensitive=True)()

    assert run_async(read) == "tester"


def test_call_context_and_exceptions_return_to_the_caller() -> None:
    context = ContextVar("bridge-test", default="unset")
    context.set("caller")
    local = Local()
    local.value = "caller"

    async def fail() -> None:
        assert context.get() == "caller"
        assert local.value == "caller"
        context.set("async")
        local.value = "async"
        observed = await sync_to_async(context.get, thread_sensitive=True)()
        assert observed == "async"
        raise ValueError("call failed")

    with pytest.raises(ValueError, match="call failed"):
        run_async(fail)
    assert context.get() == "async"
    assert local.value == "async"


def test_nested_call_from_a_sync_callback_uses_the_same_loop_and_thread() -> None:
    caller_id = get_ident()

    async def inner() -> tuple[asyncio.AbstractEventLoop, int]:
        sync_thread = await sync_to_async(get_ident, thread_sensitive=True)()
        return asyncio.get_running_loop(), sync_thread

    def callback() -> tuple[asyncio.AbstractEventLoop, int]:
        assert get_ident() == caller_id
        previous_state = SyncToAsync.threadlocal.__dict__.copy()
        result = run_async(inner)
        assert SyncToAsync.threadlocal.__dict__ == previous_state
        assert SyncToAsync.threadlocal.task_context is previous_state["task_context"]
        return result

    async def outer() -> tuple[
        asyncio.AbstractEventLoop, asyncio.AbstractEventLoop, int,
    ]:
        inner_loop, sync_thread = await sync_to_async(callback, thread_sensitive=True)()
        return asyncio.get_running_loop(), inner_loop, sync_thread

    outer_loop, inner_loop, sync_thread = run_async(outer)
    assert outer_loop is inner_loop
    assert sync_thread == caller_id


@pytest.mark.parametrize("fail", [False, True])
def test_asgi_host_keeps_its_original_loop_and_task_state(fail: bool) -> None:
    async def inspect_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    async def bridge_call() -> asyncio.AbstractEventLoop:
        if fail:
            raise ValueError("bridge call failed")
        return asyncio.get_running_loop()

    def sync_view() -> tuple[asyncio.AbstractEventLoop, asyncio.AbstractEventLoop]:
        before = async_to_sync(inspect_loop)()
        previous_state = SyncToAsync.threadlocal.__dict__.copy()
        if fail:
            with pytest.raises(ValueError, match="bridge call failed"):
                run_async(bridge_call)
        else:
            assert run_async(bridge_call) is not before
        assert SyncToAsync.threadlocal.__dict__ == previous_state
        assert SyncToAsync.threadlocal.task_context is previous_state["task_context"]
        after = async_to_sync(inspect_loop)()
        return before, after

    async def host() -> None:
        host_loop = asyncio.get_running_loop()
        before, after = await sync_to_async(sync_view, thread_sensitive=True)()
        assert before is host_loop
        assert after is host_loop

    asyncio.run(host())


def test_sync_thread_does_not_need_a_current_event_loop() -> None:
    def worker() -> asyncio.AbstractEventLoop:
        with pytest.raises(RuntimeError):
            asyncio.get_event_loop()

        async def get_loop() -> asyncio.AbstractEventLoop:
            return asyncio.get_running_loop()

        return run_async(get_loop)

    with ThreadPoolExecutor(max_workers=1) as executor:
        loop = executor.submit(worker).result(timeout=5)
    assert loop.is_running()


def test_async_caller_gets_an_error_before_it_can_block_the_loop() -> None:
    async def inner() -> None:
        pass

    async def outer() -> None:
        with pytest.raises(RuntimeError, match="sync thread"):
            run_async(inner)

    asyncio.run(outer())


def test_shutdown_closes_the_loop_and_a_later_call_starts_another() -> None:
    async def get_loop() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    first_loop = run_async(get_loop)
    _close_async_bridge()
    assert first_loop.is_closed()
    second_loop = run_async(get_loop)
    assert second_loop is not first_loop
    assert second_loop.is_running()


def test_shutdown_cancels_owned_background_tasks_before_closing_the_loop() -> None:
    started = Event()
    stopped = Event()

    async def background() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def start() -> asyncio.AbstractEventLoop:
        asyncio.create_task(background())
        await asyncio.sleep(0)
        return asyncio.get_running_loop()

    loop = run_async(start)
    assert started.is_set()
    _close_async_bridge()
    assert stopped.is_set()
    assert loop.is_closed()


@pytest.mark.skipif(
    not hasattr(os, "fork"), reason="The platform does not support fork.",
)
@pytest.mark.parametrize("lock_held", [False, True])
def test_fork_child_replaces_the_loop_and_inherited_startup_lock(
    lock_held: bool,
) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tests.scenarios.async_bridge", str(int(lock_held))],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
