__all__ = (
    "async_http_proxy",
    "cancellation_server",
    "codec_streaming_server",
    "early_response_http_server",
    "gated_early_response_http_server",
    "resource_gate",
    "resource_http_server",
    "secondary_resource_gate",
    "secondary_resource_http_server",
    "slow_upload_request_headers_received",
    "streaming_server",
    "timeout_http_server",
)

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext, suppress
import socket
import struct
import sys
from urllib.parse import urlsplit

import pytest

from tests.client_cancellation.conftest import cancellation_server
from tests.client_proxy.http_proxy_server import (
    PROXY_STREAM_EARLY_CLOSE_PATH,
    AsyncHTTPProxy,
    async_http_proxy,
    start_async_http_proxy,
)
from tests.client_resources.conftest import (
    resource_gate,
    resource_http_server,
    secondary_resource_gate,
    secondary_resource_http_server,
)
from tests.client_streaming.conftest import codec_streaming_server, streaming_server
from tests.client_streaming.constants import FIRST_CHUNK, GATED_STREAM_PATH
from tests.client_streaming.server import AsyncStreamingServer, start_async_streaming_server
from tests.client_timeouts.conftest import (
    early_response_http_server,
    gated_early_response_http_server,
    slow_upload_request_headers_received,
    timeout_http_server,
)
from tests.pyo3_boundary.async_future_server import EMPTY_HTTP_RESPONSE, DelayedResponseServer, delayed_response_server
from tests.support.async_http_server import _handle_request
from tests.support.async_server import serve_tcp


WATCHDOG = 3
PARTIAL_HEAD = b"GET / HTTP/1.1\r\nHost: localhost\r\n"


def _reset_on_close(peer: socket.socket) -> None:
    linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
    peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)


@asynccontextmanager
async def _connect(base_url: str) -> AsyncIterator[tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
    address = urlsplit(base_url)
    reader, writer = await asyncio.open_connection(address.hostname, address.port)
    try:
        yield reader, writer
    finally:
        writer.close()
        with suppress(ConnectionResetError):
            await writer.wait_closed()


@pytest.fixture
async def _delayed_server() -> AsyncIterator[DelayedResponseServer]:
    async with delayed_response_server(EMPTY_HTTP_RESPONSE) as server:
        yield server


@pytest.fixture
async def client_lifetime() -> AsyncIterator[AsyncExitStack]:
    async with AsyncExitStack() as clients:
        yield clients


@pytest.fixture
def content_type() -> str:
    return "text/plain; charset=utf-8"


@pytest.fixture(
    params=[
        "http_server",
        "secondary_http_server",
        "resource_http_server",
        "secondary_resource_http_server",
        "cancellation_server",
        "async_http_proxy",
        "_delayed_server",
        "streaming_server",
        "codec_streaming_server",
        "timeout_http_server",
        "early_response_http_server",
        "gated_early_response_http_server",
    ],
)
def server_url(request: pytest.FixtureRequest) -> str:
    # Resolve the real fixture after the client stack, so pytest stops the server first.
    request.getfixturevalue("client_lifetime")
    server: str | tuple[str, asyncio.Event] | AsyncHTTPProxy | AsyncStreamingServer | DelayedResponseServer = (
        request.getfixturevalue(request.param)
    )
    if isinstance(server, str):
        return server
    if isinstance(server, tuple):
        return server[0]
    return server.base_url


@pytest.fixture
async def handler_started(monkeypatch: pytest.MonkeyPatch) -> asyncio.Future[asyncio.Task[None]]:
    started = asyncio.get_running_loop().create_future()
    readuntil = asyncio.StreamReader.readuntil

    async def observed_read(reader: asyncio.StreamReader, separator: bytes) -> bytes:
        started.set_result(asyncio.current_task())
        return await readuntil(reader, separator)

    monkeypatch.setattr(asyncio.StreamReader, "readuntil", observed_read)
    return started


async def test_fixture_closes_idle_peer_and_finishes_handler(
    server_url: str,
    client_lifetime: AsyncExitStack,
    handler_started: asyncio.Future[asyncio.Task[None]],
) -> None:
    reader, writer = await client_lifetime.enter_async_context(_connect(server_url))
    writer.write(PARTIAL_HEAD)
    await writer.drain()
    handler = await asyncio.wait_for(handler_started, timeout=WATCHDOG)
    assert not handler.done()

    # A broken fixture might wait for its client. Let pytest finish teardown and report the cause.
    forced_close = asyncio.Event()

    def unblock_teardown() -> None:
        forced_close.set()
        writer.close()

    watchdog = asyncio.get_running_loop().call_later(WATCHDOG, unblock_teardown)

    async def verify_shutdown() -> None:
        watchdog.cancel()
        assert not forced_close.is_set(), "fixture teardown required the client to close first"
        assert handler.done()
        with suppress(ConnectionResetError):
            assert await asyncio.wait_for(reader.read(1), timeout=WATCHDOG) == b""

    client_lifetime.push_async_callback(verify_shutdown)


@pytest.fixture
def disconnect_server(request: pytest.FixtureRequest) -> AsyncHTTPProxy | DelayedResponseServer:
    server: AsyncHTTPProxy | DelayedResponseServer = request.getfixturevalue(request.param)
    return server


@pytest.mark.parametrize(
    ("disconnect_server", "request_bytes"),
    [
        pytest.param("_delayed_server", PARTIAL_HEAD, id="delayed-partial-header"),
        pytest.param("async_http_proxy", PARTIAL_HEAD, id="proxy-partial-header"),
        pytest.param("async_http_proxy", b"POST / HTTP/1.1\r\nContent-Length: 5\r\n\r\nab", id="proxy-partial-body"),
    ],
    indirect=["disconnect_server"],
)
@pytest.mark.parametrize("reset", [False, True], ids=["fin", "reset"])
async def test_fixture_discards_incomplete_request_before_shutdown(
    disconnect_server: AsyncHTTPProxy | DelayedResponseServer,
    request_bytes: bytes,
    handler_started: asyncio.Future[asyncio.Task[None]],
    *,
    reset: bool,
) -> None:
    async with asyncio.timeout(WATCHDOG):
        async with _connect(disconnect_server.base_url) as (_, writer):
            writer.write(request_bytes)
            await writer.drain()
            handler = await handler_started
            if reset:
                _reset_on_close(writer.get_extra_info("socket"))
        await asyncio.wait((handler,))
    if isinstance(disconnect_server, DelayedResponseServer):
        assert not disconnect_server.request_seen.is_set()
    else:
        assert disconnect_server.requests == []


@pytest.mark.parametrize(
    ("disconnect_server", "path"),
    [
        pytest.param("_delayed_server", "/", id="delayed"),
        pytest.param("async_http_proxy", "/", id="proxy"),
        pytest.param("async_http_proxy", PROXY_STREAM_EARLY_CLOSE_PATH, id="proxy-stream"),
    ],
    indirect=["disconnect_server"],
)
async def test_fixture_accepts_peer_reset_during_response(
    disconnect_server: AsyncHTTPProxy | DelayedResponseServer,
    path: str,
    handler_started: asyncio.Future[asyncio.Task[None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drain_started = asyncio.Event()
    drain = asyncio.StreamWriter.drain

    async def drain_after_reset(writer: asyncio.StreamWriter) -> None:
        drain_started.set()
        # Wait for the server's transport to observe the TCP reset before draining it.
        with pytest.raises(ConnectionResetError):
            await writer.wait_closed()
        await drain(writer)

    monkeypatch.setattr(asyncio.StreamWriter, "drain", drain_after_reset)
    async with asyncio.timeout(WATCHDOG):
        with socket.socket() as peer:
            peer.settimeout(0)
            loop = asyncio.get_running_loop()
            address = urlsplit(disconnect_server.base_url)
            assert address.hostname is not None
            assert address.port is not None
            await loop.sock_connect(peer, (address.hostname, address.port))
            await loop.sock_sendall(peer, f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
            if isinstance(disconnect_server, DelayedResponseServer):
                await disconnect_server.request_seen.wait()
                disconnect_server.release_response.set()
            await drain_started.wait()
            _reset_on_close(peer)
        handler = await handler_started
        await asyncio.shield(handler)


@pytest.mark.parametrize("fail_scenario", [False, True], ids=["early-exit", "scenario-error"])
async def test_streaming_exit_after_first_chunk_releases_gate(*, fail_scenario: bool) -> None:
    failure = RuntimeError("stream scenario interrupted")
    async with asyncio.timeout(WATCHDOG), AsyncExitStack() as clients:
        with pytest.raises(RuntimeError, match="stream scenario interrupted") if fail_scenario else nullcontext():
            async with start_async_streaming_server() as server:
                reader, writer = await clients.enter_async_context(_connect(server.base_url))
                writer.write(f"GET {GATED_STREAM_PATH} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
                await writer.drain()
                await reader.readuntil(FIRST_CHUNK + b"\r\n")
                assert server.first_chunk_sent.is_set()
                assert not server.release_tail.is_set()
                if fail_scenario:
                    raise failure
        assert server.release_tail.is_set()
        with suppress(ConnectionResetError):
            await reader.read()
            assert reader.at_eof()


async def test_stopping_one_server_preserves_another_servers_active_request() -> None:
    async with (
        asyncio.timeout(WATCHDOG),
        AsyncExitStack() as clients,
        delayed_response_server(EMPTY_HTTP_RESPONSE) as remaining,
    ):
        reader, writer = await clients.enter_async_context(_connect(remaining.base_url))
        writer.write(PARTIAL_HEAD + b"\r\n")
        await writer.drain()
        await remaining.request_seen.wait()
        async with delayed_response_server(None) as stopping:
            _, other_writer = await clients.enter_async_context(_connect(stopping.base_url))
            other_writer.write(PARTIAL_HEAD + b"\r\n")
            await other_writer.drain()
            await stopping.request_seen.wait()
        remaining.release_response.set()
        assert await reader.read() == EMPTY_HTTP_RESPONSE


async def test_malformed_upload_chunk_size_surfaces_at_shutdown() -> None:
    async with asyncio.timeout(WATCHDOG), AsyncExitStack() as servers:
        port = await servers.enter_async_context(serve_tcp(_handle_request))
        async with _connect(f"http://127.0.0.1:{port}") as (reader, writer):
            writer.write(b"POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\ninvalid-chunk-size\r\n")
            await writer.drain()
            assert await reader.read() == b""
        with pytest.raises(ValueError, match="invalid-chunk-size"):
            await servers.aclose()


@pytest.mark.parametrize(
    ("request_bytes", "error_type", "message"),
    [
        pytest.param(b"POST / HTTP/1.1\r\nContent-Length: invalid\r\n\r\n", ValueError, "invalid", id="invalid-length"),
        pytest.param(
            b"GET /proxy-redirect HTTP/1.1\r\n\r\n",
            AssertionError,
            "missing 'location' query parameter",
            id="missing-redirect-location",
        ),
    ],
)
async def test_invalid_proxy_request_surfaces_at_shutdown(
    request_bytes: bytes,
    error_type: type[Exception],
    message: str,
) -> None:
    async with asyncio.timeout(WATCHDOG), AsyncExitStack() as servers:
        proxy = await servers.enter_async_context(start_async_http_proxy())
        async with _connect(proxy.base_url) as (reader, writer):
            writer.write(request_bytes)
            await writer.drain()
            assert await reader.read() == b""
        with pytest.raises(error_type, match=message):
            await servers.aclose()
