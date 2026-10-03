from __future__ import annotations

import asyncio
import os
import signal
import sys
import traceback
from threading import get_ident

from asgiref.sync import sync_to_async

from agentic_django import async_bridge


async def inspect_call() -> tuple[asyncio.AbstractEventLoop, int]:
    sync_thread = await sync_to_async(get_ident, thread_sensitive=True)()
    return asyncio.get_running_loop(), sync_thread


def main() -> None:
    parent_loop, parent_sync_thread = async_bridge.run_async(inspect_call)
    assert parent_sync_thread == get_ident()
    lock_held = bool(int(sys.argv[1]))
    if lock_held:
        async_bridge._startup_lock.acquire()
    child_pid = os.fork()
    if child_pid == 0:
        signal.alarm(10)
        try:
            child_loop, child_sync_thread = async_bridge.run_async(inspect_call)
            assert child_loop is not parent_loop
            assert child_sync_thread == get_ident()
            assert child_loop.is_running()
            async_bridge._close_async_bridge()
        except BaseException:
            traceback.print_exc()
            os._exit(1)
        os._exit(0)
    if lock_held:
        async_bridge._startup_lock.release()
    _, status = os.waitpid(child_pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0, status
    same_loop, same_sync_thread = async_bridge.run_async(inspect_call)
    assert same_loop is parent_loop
    assert same_sync_thread == get_ident()
    async_bridge._close_async_bridge()


if __name__ == "__main__":
    main()
