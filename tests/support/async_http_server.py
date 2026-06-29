__all__ = ("http_server", "secondary_http_server")

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from urllib.parse import urlsplit

import pytest

from tests.http_body_scenarios import write_async_body_safety_response
from tests.support.raw_responses import raw_http_server_response


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    head = await reader.readuntil(b"\r\n\r\n")
    headers = head.decode("iso-8859-1")
    length = 0
    chunked = False
    for line in headers.split("\r\n"):
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            length = int(value.strip())
        if name.lower() == "transfer-encoding" and value.strip().lower() == "chunked":
            chunked = True
    if chunked:
        body = await _read_chunked_body(reader)
    else:
        body = await reader.readexactly(length) if length else b""
    return headers, body


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    body = bytearray()
    while True:
        size_line = await reader.readline()
        size = int(size_line.split(b";", maxsplit=1)[0].strip(), 16)
        if size == 0:
            await _read_trailers(reader)
            return bytes(body)
        body.extend(await reader.readexactly(size))
        await reader.readexactly(2)


async def _read_trailers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b""):
            return


async def _start_async_http_server() -> tuple[asyncio.AbstractServer, str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            headers, body = await _read_request(reader)
            _method, target, _version = headers.splitlines()[0].split()
            path = urlsplit(target).path
            if not await write_async_body_safety_response(path, writer):
                writer.write(raw_http_server_response(headers, body))
                await writer.drain()
        except OSError:
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()
    return server, f"http://{host}:{port}"


@pytest.fixture
async def http_server() -> AsyncIterator[str]:
    server, base_url = await _start_async_http_server()
    try:
        yield base_url
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def secondary_http_server() -> AsyncIterator[str]:
    server, base_url = await _start_async_http_server()
    try:
        yield base_url
    finally:
        server.close()
        await server.wait_closed()
