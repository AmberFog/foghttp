__all__ = (
    "DelayedResponseServer",
    "cache_async_client_future_setters",
    "delayed_response_server",
)

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

import foghttp
from foghttp.status_codes.success import OK
from tests.support.async_server import serve_tcp

from .constants import WAIT_TIMEOUT


EMPTY_HTTP_RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"


@dataclass(frozen=True, slots=True)
class DelayedResponseServer:
    base_url: str
    request_seen: asyncio.Event
    release_response: asyncio.Event


@asynccontextmanager
async def delayed_response_server(
    response: bytes | None,
) -> AsyncIterator[DelayedResponseServer]:
    request_seen = asyncio.Event()
    release_response = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, ConnectionResetError):
            return
        request_seen.set()
        await release_response.wait()
        if response is not None:
            with suppress(BrokenPipeError, ConnectionResetError):
                writer.write(response)
                await writer.drain()

    async with serve_tcp(handle) as port:
        try:
            yield DelayedResponseServer(
                base_url=f"http://127.0.0.1:{port}",
                request_seen=request_seen,
                release_response=release_response,
            )
        finally:
            release_response.set()


async def cache_async_client_future_setters(client: foghttp.AsyncClient) -> None:
    async with delayed_response_server(EMPTY_HTTP_RESPONSE) as server:
        task = asyncio.create_task(client.get(server.base_url))
        await asyncio.wait_for(server.request_seen.wait(), timeout=WAIT_TIMEOUT)
        server.release_response.set()
        response = await asyncio.wait_for(task, timeout=WAIT_TIMEOUT)

    if response.status_code != OK:
        msg = "warm-up request did not complete successfully"
        raise AssertionError(msg)
