import asyncio
from contextlib import suppress
import socket

import pytest

from tests.support.async_server import serve_tcp


async def test_teardown_owns_socket_accepted_before_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    accepted: asyncio.Future[tuple[socket.socket, socket.socket]] = loop.create_future()
    release = asyncio.Event()
    socket_accept = socket.socket.accept
    open_connection = asyncio.open_connection
    started = asyncio.Event()

    def record_accept(listener: socket.socket) -> tuple[socket.socket, object]:
        peer, address = socket_accept(listener)
        accepted.set_result((listener, peer))
        return peer, address

    async def paused_handoff(*, sock: socket.socket) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        await release.wait()
        return await open_connection(sock=sock)

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        started.set()

    with socket.socket() as client:
        client.settimeout(0)
        async with asyncio.timeout(3):
            async with serve_tcp(handle) as port:
                monkeypatch.setattr(socket.socket, "accept", record_accept)
                monkeypatch.setattr(asyncio, "open_connection", paused_handoff)
                connect = asyncio.create_task(loop.sock_connect(client, ("127.0.0.1", port)))
                listener, peer = await accepted
                # Resume delivery only after the owner has entered teardown.
                loop.call_soon(release.set)
            await connect
            assert listener.fileno() == -1
            assert peer.fileno() == -1
            with suppress(ConnectionResetError):
                assert await loop.sock_recv(client, 1) == b""
    assert not started.is_set()


@pytest.mark.parametrize("hold_handoff", [True, False], ids=["stream-setup", "handler-before-first-step"])
async def test_teardown_owns_stream_before_first_handler_step(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hold_handoff: bool,
) -> None:
    loop = asyncio.get_running_loop()
    stream_ready: asyncio.Future[asyncio.StreamWriter] = loop.create_future()
    release = asyncio.Event()
    open_connection = asyncio.open_connection
    started = asyncio.Event()

    async def make_stream(*, sock: socket.socket) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await open_connection(sock=sock)
        stream_ready.set_result(writer)
        if hold_handoff:
            await release.wait()
        return reader, writer

    async def handle(_reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        started.set()

    monkeypatch.setattr(asyncio, "open_connection", make_stream)
    with socket.socket() as client:
        client.settimeout(0)
        async with asyncio.timeout(3):
            async with serve_tcp(handle) as port:
                connect = asyncio.create_task(loop.sock_connect(client, ("127.0.0.1", port)))
                writer = await stream_ready
                # Without the gate the handler was scheduled behind this wakeup.
                loop.call_soon(release.set)
            await connect
            assert writer.get_extra_info("socket").fileno() == -1
            with suppress(ConnectionResetError):
                assert await loop.sock_recv(client, 1) == b""
    assert not started.is_set()


async def test_teardown_joins_handlers_when_new_connections_are_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    started = loop.create_future()
    finished = asyncio.Event()

    async def handle(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        started.set_result(writer.get_extra_info("socket"))
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    def deny_connect(_sock: socket.socket, _address: object) -> None:
        message = "outbound connections are disabled"
        raise PermissionError(message)

    with socket.socket() as peer:
        peer.settimeout(0)
        async with asyncio.timeout(3):
            async with serve_tcp(handle) as port:
                await loop.sock_connect(peer, ("127.0.0.1", port))
                server_socket = await started
                monkeypatch.setattr(socket.socket, "connect", deny_connect)
            assert finished.is_set()
            assert server_socket.fileno() == -1
            assert await loop.sock_recv(peer, 1) == b""
