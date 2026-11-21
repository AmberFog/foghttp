__all__ = ("serve_tcp",)

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
import selectors
import socket
from typing import Any


_Handler = Callable[[asyncio.StreamReader, asyncio.StreamWriter], Coroutine[Any, Any, None]]
_Connection = tuple[asyncio.Task[None], asyncio.StreamWriter]
_SHUTDOWN = object()


def _start(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    try:
        return asyncio.create_task(coro)
    except BaseException:
        coro.close()
        raise


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with suppress(ConnectionError):
        await writer.wait_closed()


async def _finish_connection(handler: asyncio.Task[None], writer: asyncio.StreamWriter) -> None:
    # This task owns the writer even when the handler is cancelled before its first step.
    try:
        await handler
    except asyncio.CancelledError as exc:
        if exc.args != (_SHUTDOWN,):
            raise
    finally:
        await _close_writer(writer)


def _task_error(task: asyncio.Task[None]) -> BaseException | None:
    try:
        return task.exception()
    except asyncio.CancelledError as exc:
        return exc


class _TCPServer:
    def __init__(self, handle: _Handler, stop: socket.socket) -> None:
        self.handle = handle
        self.stop = stop
        self.closing = False
        self.connections: dict[asyncio.Task[None], _Connection] = {}
        self.errors: list[BaseException] = []

    async def run(self, listener: socket.socket, signal: socket.socket) -> None:
        try:
            await self._accept(listener, signal)
        finally:
            listener.close()
            self.stop_handlers()
            if self.connections:
                await asyncio.wait(tuple(self.connections))

    async def _accept(self, listener: socket.socket, signal: socket.socket) -> None:
        loop = asyncio.get_running_loop()
        with selectors.DefaultSelector() as ready, ThreadPoolExecutor(max_workers=1) as waiter:
            ready.register(listener, selectors.EVENT_READ)
            ready.register(signal, selectors.EVENT_READ)
            try:
                while not self.closing:
                    # Only readiness is polled off-loop. Accept and stream ownership stay on this loop.
                    await loop.run_in_executor(waiter, ready.select)
                    await self._accept_ready(listener)
            finally:
                # Release the selector before joining its worker, including on cancellation.
                self.stop_handlers()

    async def _accept_ready(self, listener: socket.socket) -> None:
        if self.closing:
            return
        try:
            peer, _ = listener.accept()
        except (BlockingIOError, InterruptedError, ConnectionAbortedError):
            return
        try:
            reader, writer = await asyncio.open_connection(sock=peer)
        except BaseException:
            peer.close()
            raise
        await self._dispatch(reader, writer)

    async def _dispatch(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.closing:
            await _close_writer(writer)
            return
        try:
            handler = _start(self.handle(reader, writer))
        except BaseException:
            await _close_writer(writer)
            raise
        try:
            finished = _start(_finish_connection(handler, writer))
        except BaseException:
            handler.cancel(_SHUTDOWN)
            await _finish_connection(handler, writer)
            raise
        self.connections[finished] = handler, writer
        finished.add_done_callback(self._retire)

    def _retire(self, finished: asyncio.Task[None]) -> None:
        del self.connections[finished]
        error = _task_error(finished)
        if error is not None:
            self.errors.append(error)

    def stop_handlers(self) -> None:
        if self.closing:
            return
        self.closing = True
        self.stop.close()
        for handler, writer in self.connections.values():
            writer.transport.abort()
            if not handler.cancelling():
                handler.cancel(_SHUTDOWN)


async def _join_cleanup(
    owner: asyncio.Task[None],
    errors: list[BaseException],
    scenario_error: BaseException | None,
) -> None:
    cancelled = scenario_error if isinstance(scenario_error, asyncio.CancelledError) else None
    while not owner.done():
        try:
            await asyncio.wait((owner,))
        except asyncio.CancelledError as exc:
            if cancelled is None:
                cancelled = exc

    owner_error = _task_error(owner)
    if owner_error is not None:
        errors.append(owner_error)
    if scenario_error is not None and scenario_error is not cancelled and (errors or cancelled):
        errors.insert(0, scenario_error)

    _raise_failures(errors, cancelled)


def _raise_failures(errors: list[BaseException], cancelled: asyncio.CancelledError | None) -> None:
    cause: BaseException | None = None
    if len(errors) == 1:
        cause = errors[0]
    elif errors:
        message = "test server and scenario failures"
        cause = BaseExceptionGroup(message, errors)
    if cancelled is not None:
        if cause is None:
            raise cancelled
        raise cancelled from cause
    if cause is not None:
        raise cause


@asynccontextmanager
async def serve_tcp(handle: _Handler) -> AsyncIterator[int]:
    """Own one loopback listener, its accepted sockets and handler outcomes until context exit."""
    with socket.create_server(("127.0.0.1", 0)) as listener:
        signal, stop = socket.socketpair()
        with signal, stop:
            listener.settimeout(0)
            server = _TCPServer(handle, stop)
            owner = _start(server.run(listener, signal))
            scenario_error = None
            try:
                yield listener.getsockname()[1]
            except BaseException as exc:
                scenario_error = exc
                raise
            finally:
                server.stop_handlers()
                await _join_cleanup(owner, server.errors, scenario_error)
