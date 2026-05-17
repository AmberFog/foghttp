import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from urllib.parse import urlsplit

import pytest

from foghttp.methods import HEAD
from foghttp.status_codes.success import OK

from .constants import OK_BODY, SLOW_BODY_PATH, SLOW_HEADERS_PATH, SLOW_RESPONSE_DELAY


@pytest.fixture
async def cancellation_server() -> AsyncIterator[str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_head = await reader.readuntil(b"\r\n\r\n")
            request_line = request_head.decode("iso-8859-1").splitlines()[0]
            method, target, _version = request_line.split()
            path = urlsplit(target).path

            if path == SLOW_HEADERS_PATH:
                if await _wait_for_disconnect(reader):
                    return
                await _write_response(writer, OK_BODY)
                return

            if path == SLOW_BODY_PATH:
                await _write_headers(writer, len(OK_BODY))
                if await _wait_for_disconnect(reader):
                    return
                writer.write(OK_BODY)
                await writer.drain()
                return

            body = b"" if method == HEAD else OK_BODY
            await _write_response(writer, body)
        except (asyncio.IncompleteReadError, OSError):
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


async def _write_headers(writer: asyncio.StreamWriter, content_length: int) -> None:
    writer.write(
        f"HTTP/1.1 {OK} OK\r\ncontent-length: {content_length}\r\nconnection: close\r\n\r\n".encode(),
    )
    await writer.drain()


async def _write_response(writer: asyncio.StreamWriter, body: bytes) -> None:
    await _write_headers(writer, len(body))
    writer.write(body)
    await writer.drain()


async def _wait_for_disconnect(reader: asyncio.StreamReader) -> bool:
    try:
        await asyncio.wait_for(reader.read(), timeout=SLOW_RESPONSE_DELAY)
    except TimeoutError:
        return False
    return True
