__all__ = (
    "AsyncStreamingServer",
    "SyncStreamingServer",
    "start_async_streaming_server",
    "start_sync_streaming_server",
)

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit

from foghttp.status_codes.success import OK

from .constants import (
    BROKEN_READY_TAIL_STREAM_PATH,
    EMPTY_STREAM_PATH,
    FIRST_CHUNK,
    GATED_STREAM_PATH,
    SECOND_CHUNK,
    SLOW_TAIL_DELAY,
    SLOW_TAIL_STREAM_PATH,
    TAIL_WAIT_TIMEOUT,
)


@dataclass(frozen=True, slots=True)
class AsyncStreamingServer:
    base_url: str
    first_chunk_sent: asyncio.Event
    release_tail: asyncio.Event


@dataclass(frozen=True, slots=True)
class SyncStreamingServer:
    base_url: str
    first_chunk_sent: threading.Event
    release_tail: threading.Event


class SyncStreamWriter(Protocol):
    def write(self, data: bytes) -> object: ...

    def flush(self) -> None: ...


class SyncStreamingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        error_type, _error_value, _traceback = sys.exc_info()
        if error_type is not None and issubclass(error_type, OSError):
            return
        super().handle_error(request, client_address)


@asynccontextmanager
async def start_async_streaming_server() -> AsyncIterator[AsyncStreamingServer]:
    first_chunk_sent = asyncio.Event()
    release_tail = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_head = await reader.readuntil(b"\r\n\r\n")
            request_line = request_head.decode("iso-8859-1").splitlines()[0]
            _method, target, _version = request_line.split()
            path = urlsplit(target).path
            await _write_stream_response(
                path=path,
                writer=writer,
                first_chunk_sent=first_chunk_sent,
                release_tail=release_tail,
            )
        except OSError:
            return
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()
    try:
        yield AsyncStreamingServer(
            base_url=f"http://{host}:{port}",
            first_chunk_sent=first_chunk_sent,
            release_tail=release_tail,
        )
    finally:
        server.close()
        await server.wait_closed()


@contextmanager
def start_sync_streaming_server() -> Iterator[SyncStreamingServer]:
    first_chunk_sent = threading.Event()
    release_tail = threading.Event()

    class SyncStreamingHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            with suppress(BrokenPipeError, ConnectionResetError, OSError):
                _write_sync_stream_response(
                    path=path,
                    writer=self.wfile,
                    first_chunk_sent=first_chunk_sent,
                    release_tail=release_tail,
                )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = SyncStreamingHTTPServer(("127.0.0.1", 0), SyncStreamingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield SyncStreamingServer(
            base_url=f"http://{host}:{port}",
            first_chunk_sent=first_chunk_sent,
            release_tail=release_tail,
        )
    finally:
        release_tail.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


async def _write_stream_response(
    *,
    path: str,
    writer: asyncio.StreamWriter,
    first_chunk_sent: asyncio.Event,
    release_tail: asyncio.Event,
) -> None:
    if path == GATED_STREAM_PATH:
        await _write_gated_stream(
            writer=writer,
            first_chunk_sent=first_chunk_sent,
            release_tail=release_tail,
        )
        return
    if path == SLOW_TAIL_STREAM_PATH:
        await _write_slow_tail_stream(writer=writer, first_chunk_sent=first_chunk_sent)
        return
    if path == BROKEN_READY_TAIL_STREAM_PATH:
        await _write_broken_ready_tail_stream(writer=writer, first_chunk_sent=first_chunk_sent)
        return
    if path == EMPTY_STREAM_PATH:
        writer.write(_raw_response(content_length=0))
        await writer.drain()
        return

    writer.write(_raw_response(content_length=0))
    await writer.drain()


def _write_sync_stream_response(
    *,
    path: str,
    writer: SyncStreamWriter,
    first_chunk_sent: threading.Event,
    release_tail: threading.Event,
) -> None:
    if path == GATED_STREAM_PATH:
        _write_sync_gated_stream(
            writer=writer,
            first_chunk_sent=first_chunk_sent,
            release_tail=release_tail,
        )
        return
    if path == SLOW_TAIL_STREAM_PATH:
        _write_sync_slow_tail_stream(writer=writer, first_chunk_sent=first_chunk_sent)
        return
    if path == BROKEN_READY_TAIL_STREAM_PATH:
        _write_sync_broken_ready_tail_stream(writer=writer, first_chunk_sent=first_chunk_sent)
        return
    if path == EMPTY_STREAM_PATH:
        writer.write(_raw_response(content_length=0))
        writer.flush()
        return

    writer.write(_raw_response(content_length=0))
    writer.flush()


async def _write_gated_stream(
    *,
    writer: asyncio.StreamWriter,
    first_chunk_sent: asyncio.Event,
    release_tail: asyncio.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    await writer.drain()
    first_chunk_sent.set()
    with suppress(TimeoutError):
        await asyncio.wait_for(release_tail.wait(), timeout=TAIL_WAIT_TIMEOUT)
    writer.write(_chunk(SECOND_CHUNK))
    writer.write(_last_chunk())
    await writer.drain()


def _write_sync_gated_stream(
    *,
    writer: SyncStreamWriter,
    first_chunk_sent: threading.Event,
    release_tail: threading.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    writer.flush()
    first_chunk_sent.set()
    release_tail.wait(timeout=TAIL_WAIT_TIMEOUT)
    writer.write(_chunk(SECOND_CHUNK))
    writer.write(_last_chunk())
    writer.flush()


async def _write_slow_tail_stream(
    *,
    writer: asyncio.StreamWriter,
    first_chunk_sent: asyncio.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    await writer.drain()
    first_chunk_sent.set()
    await asyncio.sleep(SLOW_TAIL_DELAY)
    writer.write(_chunk(SECOND_CHUNK))
    writer.write(_last_chunk())
    await writer.drain()


async def _write_broken_ready_tail_stream(
    *,
    writer: asyncio.StreamWriter,
    first_chunk_sent: asyncio.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    writer.write(_chunk(SECOND_CHUNK))
    await writer.drain()
    first_chunk_sent.set()


def _write_sync_slow_tail_stream(
    *,
    writer: SyncStreamWriter,
    first_chunk_sent: threading.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    writer.flush()
    first_chunk_sent.set()
    time.sleep(SLOW_TAIL_DELAY)
    writer.write(_chunk(SECOND_CHUNK))
    writer.write(_last_chunk())
    writer.flush()


def _write_sync_broken_ready_tail_stream(
    *,
    writer: SyncStreamWriter,
    first_chunk_sent: threading.Event,
) -> None:
    writer.write(_chunked_response_head())
    writer.write(_chunk(FIRST_CHUNK))
    writer.write(_chunk(SECOND_CHUNK))
    writer.flush()
    first_chunk_sent.set()


def _raw_response(*, content_length: int) -> bytes:
    return (f"HTTP/1.1 {OK} OK\r\ncontent-length: {content_length}\r\nconnection: close\r\n\r\n").encode()


def _chunked_response_head() -> bytes:
    return (
        f"HTTP/1.1 {OK} OK\r\n"
        "content-type: application/octet-stream\r\n"
        "transfer-encoding: chunked\r\n"
        "connection: close\r\n"
        "\r\n"
    ).encode()


def _chunk(content: bytes) -> bytes:
    return f"{len(content):x}\r\n".encode() + content + b"\r\n"


def _last_chunk() -> bytes:
    return b"0\r\n\r\n"
