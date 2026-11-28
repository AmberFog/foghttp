import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler
import socket
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.support.async_server import serve_tcp
from tests.support.sync_server import SyncHTTPServer

from .constants import (
    OK_BODY,
    REDIRECT_LOCATION_QUERY_PARAM,
    REDIRECT_STATUS_QUERY_PARAM,
    REDIRECT_TO_LOCATION_PATH,
    SLOW_RESPONSE_PATH,
)
from .gates import AsyncResponseGate, SyncResponseGate


@pytest.fixture
def resource_gate() -> AsyncResponseGate:
    return AsyncResponseGate()


@pytest.fixture
def secondary_resource_gate() -> AsyncResponseGate:
    return AsyncResponseGate()


@pytest.fixture
def sync_resource_gate() -> SyncResponseGate:
    return SyncResponseGate()


@pytest.fixture
def secondary_sync_resource_gate() -> SyncResponseGate:
    return SyncResponseGate()


@pytest.fixture
async def resource_http_server(resource_gate: AsyncResponseGate) -> AsyncIterator[str]:
    async with serve_tcp(partial(_handle_resource_request, gate=resource_gate)) as port:
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
async def secondary_resource_http_server(secondary_resource_gate: AsyncResponseGate) -> AsyncIterator[str]:
    async with serve_tcp(partial(_handle_resource_request, gate=secondary_resource_gate)) as port:
        yield f"http://127.0.0.1:{port}"


@pytest.fixture
def sync_resource_http_server(sync_resource_gate: SyncResponseGate) -> Iterator[str]:
    with _sync_resource_server(sync_resource_gate) as url:
        yield url


@pytest.fixture
def secondary_sync_resource_http_server(secondary_sync_resource_gate: SyncResponseGate) -> Iterator[str]:
    with _sync_resource_server(secondary_sync_resource_gate) as url:
        yield url


@contextmanager
def _sync_resource_server(gate: SyncResponseGate) -> Iterator[str]:
    host = "127.0.0.1"
    server = SyncHTTPServer((host, 0), partial(ResourceHTTPHandler, gate=gate))
    thread = server.start()
    try:
        yield f"http://{host}:{server.server_port}"
    finally:
        gate.release_response.set()
        server.stop(thread)


async def _handle_resource_request(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    gate: AsyncResponseGate,
) -> None:
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
            gate.request_started.set()
            await gate.release_response.wait()
        await _write_ok_response(writer)
    except (asyncio.IncompleteReadError, OSError):
        return


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

    def __init__(
        self,
        request: socket.socket,
        client_address: tuple[str, int],
        server: SyncHTTPServer,
        *,
        gate: SyncResponseGate,
    ) -> None:
        self._gate = gate
        super().__init__(request, client_address, server)

    def do_GET(self) -> None:
        redirect = _redirect_to_location(self.path)
        if redirect is not None:
            status_code, location = redirect
            self._write_redirect_response(status_code, location)
            return

        target_parts = urlsplit(self.path)
        if target_parts.path == SLOW_RESPONSE_PATH:
            self._gate.request_started.set()
            self._gate.release_response.wait()

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
