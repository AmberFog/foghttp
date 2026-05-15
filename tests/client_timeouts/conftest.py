import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import pytest

from foghttp.status_codes.success import OK

from .constants import SLOW_RESPONSE_DELAY, SLOW_RESPONSE_PATH


OK_BODY = b"OK"


@pytest.fixture
async def timeout_http_server() -> AsyncIterator[str]:
    server = await _start_async_timeout_server()
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


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


async def _start_async_timeout_server() -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            request_line = head.decode("iso-8859-1").splitlines()[0]
            _method, target, _version = request_line.split()
            if urlsplit(target).path == SLOW_RESPONSE_PATH:
                await asyncio.sleep(SLOW_RESPONSE_DELAY)

            writer.write(_raw_ok_response())
            await writer.drain()
        except (asyncio.IncompleteReadError, OSError, ValueError):
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


def _raw_ok_response() -> bytes:
    return (f"HTTP/1.1 {OK} OK\r\ncontent-length: {len(OK_BODY)}\r\nconnection: close\r\n\r\n").encode() + OK_BODY


class TimeoutHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if urlsplit(self.path).path == SLOW_RESPONSE_PATH:
            time.sleep(SLOW_RESPONSE_DELAY)

        try:
            self.send_response(OK)
            self.send_header("content-length", str(len(OK_BODY)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(OK_BODY)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, _format: str, *_args: Any) -> None:
        return
