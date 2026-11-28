import asyncio
from contextlib import AsyncExitStack, suppress
import inspect
import socket
from typing import Any

import pytest

from tests.support.async_server import serve_tcp


@pytest.mark.parametrize("tasks_before_failure", [0, 1], ids=["handler", "handler-finalizer"])
async def test_refused_task_closes_coroutine_peer_and_started_handler(tasks_before_failure: int) -> None:
    loop = asyncio.get_running_loop()
    original_factory = loop.get_task_factory()
    failure = RuntimeError("connection task refused")
    created: list[asyncio.Task[Any]] = []
    rejected: list[object] = []

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        await asyncio.Event().wait()

    def reject_task(
        task_loop: asyncio.AbstractEventLoop,
        coroutine: Any,
        **kwargs: Any,
    ) -> asyncio.Task[Any]:
        # ProactorEventLoop can schedule its own accept task before our handler.
        if coroutine.cr_code is not handle.__code__ and (not created or rejected):
            return asyncio.Task(coroutine, loop=task_loop, **kwargs)
        if len(created) == tasks_before_failure:
            rejected.append(coroutine)
            raise failure
        task = asyncio.Task(coroutine, loop=task_loop, **kwargs)
        created.append(task)
        return task

    with socket.socket() as peer:
        peer.settimeout(0)
        async with asyncio.timeout(3), AsyncExitStack() as servers:
            port = await servers.enter_async_context(serve_tcp(handle))
            loop.set_task_factory(reject_task)
            try:
                await loop.sock_connect(peer, ("127.0.0.1", port))
                with suppress(ConnectionResetError):
                    assert await loop.sock_recv(peer, 1) == b""
            finally:
                loop.set_task_factory(original_factory)
            with pytest.raises(RuntimeError, match="connection task refused") as raised:
                await servers.aclose()

    assert raised.value is failure
    assert len(rejected) == 1
    assert inspect.iscoroutine(rejected[0])
    assert inspect.getcoroutinestate(rejected[0]) == inspect.CORO_CLOSED
    assert len(created) == tasks_before_failure
    assert all(task.done() for task in created)
