import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK

from .constants import (
    OK_BODY,
    REDIRECT_LOCATION_QUERY_PARAM,
    REDIRECT_STATUS_QUERY_PARAM,
    REDIRECT_TO_LOCATION_PATH,
    SLOW_RESPONSE_DELAY,
    SLOW_RESPONSE_PATH,
)


@pytest.fixture
async def resource_http_server() -> AsyncIterator[str]:
    server = await _start_async_resource_server()
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def secondary_resource_http_server() -> AsyncIterator[str]:
    server = await _start_async_resource_server()
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def sync_resource_http_server() -> Iterator[str]:
    server, thread = _start_sync_resource_server()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.fixture
def secondary_sync_resource_http_server() -> Iterator[str]:
    server, thread = _start_sync_resource_server()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


async def _start_async_resource_server() -> asyncio.AbstractServer:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            request_line = head.decode("iso-8859-1").splitlines()[0]
            _method, target, _version = request_line.split()
            redirect = _redirect_to_location(target)
            if redirect is not None:
                status_code, location = redirect
                await _write_redirect_response(writer, status_code, location)
                return

            target_parts = urlsplit(target)
            if target_parts.path == SLOW_RESPONSE_PATH:
                await asyncio.sleep(SLOW_RESPONSE_DELAY)
            await _write_ok_response(writer)
        except (asyncio.IncompleteReadError, OSError):
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    return await asyncio.start_server(handle, "127.0.0.1", 0)


def _redirect_to_location(target: str) -> tuple[int, str] | None:
    target_parts = urlsplit(target)
    if target_parts.path != REDIRECT_TO_LOCATION_PATH:
        return None

    query = parse_qs(target_parts.query)
    location = query[REDIRECT_LOCATION_QUERY_PARAM][0]
    status_code = int(query.get(REDIRECT_STATUS_QUERY_PARAM, [FOUND])[0])
    return status_code, location


async def _write_ok_response(writer: asyncio.StreamWriter) -> None:
    writer.write(_raw_ok_response())
    await writer.drain()


async def _write_redirect_response(
    writer: asyncio.StreamWriter,
    status_code: int,
    location: str,
) -> None:
    writer.write(_raw_redirect_response(status_code, location))
    await writer.drain()


def _raw_ok_response() -> bytes:
    return (f"HTTP/1.1 {OK} OK\r\ncontent-length: {len(OK_BODY)}\r\nconnection: close\r\n\r\n").encode() + OK_BODY


def _raw_redirect_response(status_code: int, location: str) -> bytes:
    return (
        f"HTTP/1.1 {status_code} Redirect\r\nlocation: {location}\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"
    ).encode()


class ResourceHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        redirect = _redirect_to_location(self.path)
        if redirect is not None:
            status_code, location = redirect
            self._write_redirect_response(status_code, location)
            return

        target_parts = urlsplit(self.path)
        if target_parts.path == SLOW_RESPONSE_PATH:
            time.sleep(SLOW_RESPONSE_DELAY)

        self.send_response(OK)
        self.send_header("content-length", str(len(OK_BODY)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(OK_BODY)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write_redirect_response(self, status_code: int, location: str) -> None:
        self.send_response(status_code)
        self.send_header("location", location)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()


def _start_sync_resource_server() -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), ResourceHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread
