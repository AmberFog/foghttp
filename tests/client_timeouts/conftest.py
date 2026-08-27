import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import pytest

from foghttp.status_codes.client_error import PAYLOAD_TOO_LARGE
from foghttp.status_codes.success import OK

from .constants import (
    EARLY_CLOSE_RESPONSE_PATH,
    EARLY_RESPONSE_PATH,
    SLOW_RESPONSE_DELAY,
    SLOW_RESPONSE_PATH,
    SLOW_UPLOAD_HOLD_DELAY,
    SLOW_UPLOAD_PATH,
    SLOW_UPLOAD_RECEIVE_BUFFER_SIZE,
    SLOW_UPLOAD_RESPONSE_PATH,
)


OK_BODY = b"OK"


@pytest.fixture
async def timeout_http_server(
    slow_upload_request_headers_received: asyncio.Event,
) -> AsyncIterator[str]:
    handlers: set[asyncio.Task[None]] = set()
    server = await _start_async_timeout_server(slow_upload_request_headers_received, handlers)
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        await _close_async_server(server, handlers)


@pytest.fixture
async def early_response_http_server() -> AsyncIterator[str]:
    release = asyncio.Event()
    handlers: set[asyncio.Task[None]] = set()
    server = await _start_async_early_response_server(release, handlers)
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        release.set()
        await _close_async_server(server, handlers)


@pytest.fixture
def slow_upload_request_headers_received() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
def sync_timeout_http_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), TimeoutHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


async def _start_async_timeout_server(
    slow_upload_request_headers_received: asyncio.Event,
    handlers: set[asyncio.Task[None]],
) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            _set_async_receive_buffer(writer)
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                request_line = head.decode("iso-8859-1").splitlines()[0]
                _method, target, _version = request_line.split()
                path = urlsplit(target).path
                if path == SLOW_UPLOAD_RESPONSE_PATH:
                    slow_upload_request_headers_received.set()
                    writer.write(_raw_incomplete_response())
                    await writer.drain()
                    await asyncio.sleep(SLOW_UPLOAD_HOLD_DELAY)
                    return
                if path == SLOW_UPLOAD_PATH:
                    slow_upload_request_headers_received.set()
                    await asyncio.sleep(SLOW_UPLOAD_HOLD_DELAY)
                    return
                if path == SLOW_RESPONSE_PATH:
                    await asyncio.sleep(SLOW_RESPONSE_DELAY)

                writer.write(_raw_ok_response())
                await writer.drain()
        except (asyncio.IncompleteReadError, OSError, ValueError):
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(_tracked_handler(handle, handlers), "127.0.0.1", 0)


async def _start_async_early_response_server(
    release: asyncio.Event,
    handlers: set[asyncio.Task[None]],
) -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            _set_async_receive_buffer(writer)
            head = await reader.readuntil(b"\r\n\r\n")
            request_line = head.decode("iso-8859-1").splitlines()[0]
            _method, target, _version = request_line.split()
            path = urlsplit(target).path
            if path in {EARLY_CLOSE_RESPONSE_PATH, EARLY_RESPONSE_PATH}:
                writer.write(
                    _raw_early_response(connection_close=path == EARLY_CLOSE_RESPONSE_PATH),
                )
                await writer.drain()
                await release.wait()
                return

            writer.write(_raw_ok_response())
            await writer.drain()
        except (asyncio.IncompleteReadError, OSError, ValueError):
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(_tracked_handler(handle, handlers), "127.0.0.1", 0)


def _tracked_handler(
    handler: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
    handlers: set[asyncio.Task[None]],
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], None]:
    def start(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(handler(reader, writer))
        handlers.add(task)

    return start


async def _close_async_server(
    server: asyncio.AbstractServer,
    handlers: set[asyncio.Task[None]],
) -> None:
    server.close()
    await server.wait_closed()
    tasks = tuple(handlers)
    pending_tasks = {task for task in tasks if not task.done()}
    for task in pending_tasks:
        task.cancel()
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for task, result in zip(tasks, results, strict=True):
            if not isinstance(result, BaseException):
                continue
            if task in pending_tasks and isinstance(result, asyncio.CancelledError):
                continue
            raise result


def _set_async_receive_buffer(writer: asyncio.StreamWriter) -> None:
    transport_socket = writer.get_extra_info("socket")
    if transport_socket is not None:
        transport_socket.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            SLOW_UPLOAD_RECEIVE_BUFFER_SIZE,
        )


def _raw_ok_response() -> bytes:
    return (f"HTTP/1.1 {OK} OK\r\ncontent-length: {len(OK_BODY)}\r\nconnection: keep-alive\r\n\r\n").encode() + OK_BODY


def _raw_early_response(*, connection_close: bool) -> bytes:
    connection = "close" if connection_close else "keep-alive"
    return (
        f"HTTP/1.1 {PAYLOAD_TOO_LARGE} Payload Too Large\r\ncontent-length: 0\r\nconnection: {connection}\r\n\r\n"
    ).encode()


def _raw_incomplete_response() -> bytes:
    return b"HTTP/1.1 200 OK\r\ncontent-length: 1\r\nconnection: keep-alive\r\n\r\n"


class TimeoutHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        self.request.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            SLOW_UPLOAD_RECEIVE_BUFFER_SIZE,
        )
        super().setup()

    def do_GET(self) -> None:
        self._write_response()

    def do_POST(self) -> None:
        self._write_response()

    def _write_response(self) -> None:
        path = urlsplit(self.path).path
        if path in {EARLY_CLOSE_RESPONSE_PATH, EARLY_RESPONSE_PATH}:
            self.send_response(PAYLOAD_TOO_LARGE)
            self.send_header("content-length", "0")
            connection = "close" if path == EARLY_CLOSE_RESPONSE_PATH else "keep-alive"
            self.send_header("connection", connection)
            self.end_headers()
            self.wfile.flush()
            time.sleep(SLOW_UPLOAD_HOLD_DELAY)
            self.close_connection = True
            return
        if path == SLOW_UPLOAD_PATH:
            self.close_connection = True
            time.sleep(SLOW_UPLOAD_HOLD_DELAY)
            return
        if path == SLOW_UPLOAD_RESPONSE_PATH:
            self.send_response(OK)
            self.send_header("content-length", "1")
            self.send_header("connection", "keep-alive")
            self.end_headers()
            self.wfile.flush()
            time.sleep(SLOW_UPLOAD_HOLD_DELAY)
            self.close_connection = True
            return
        if path == SLOW_RESPONSE_PATH:
            time.sleep(SLOW_RESPONSE_DELAY)

        try:
            self.send_response(OK)
            self.send_header("content-length", str(len(OK_BODY)))
            self.send_header("connection", "keep-alive")
            self.end_headers()
            self.wfile.write(OK_BODY)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, _format: str, *_args: Any) -> None:
        return
