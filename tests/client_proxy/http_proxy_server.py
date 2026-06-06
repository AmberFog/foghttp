__all__ = (
    "PROXY_REDIRECT_PATH",
    "PROXY_STREAM_CHUNK",
    "PROXY_STREAM_EARLY_CLOSE_PATH",
    "AsyncHTTPProxy",
    "ProxyRequest",
    "SyncHTTPProxy",
    "async_http_proxy",
    "sync_http_proxy",
)

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.support.raw_responses import raw_response


PROXY_REDIRECT_LOCATION_PARAM = "location"
PROXY_REDIRECT_PATH = "/proxy-redirect"
PROXY_STREAM_EARLY_CLOSE_PATH = "/proxy-stream-early-close"
PROXY_STREAM_CHUNK = b"x" * 128
PROXY_STREAM_CHUNKS = 8
PROXY_STREAM_CHUNK_DELAY_SECONDS = 0.02


@dataclass(frozen=True, slots=True)
class ProxyRequest:
    request_line: str
    headers: dict[str, list[str]]
    body: bytes


@dataclass(slots=True)
class SyncHTTPProxy:
    server: ThreadingHTTPServer
    thread: threading.Thread
    base_url: str
    _requests: list[ProxyRequest] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stream_delay: threading.Event = field(default_factory=threading.Event)

    @property
    def requests(self) -> list[ProxyRequest]:
        with self._lock:
            return list(self._requests)

    def append(self, request: ProxyRequest) -> None:
        with self._lock:
            self._requests.append(request)

    def wait_between_stream_chunks(self) -> None:
        self._stream_delay.wait(PROXY_STREAM_CHUNK_DELAY_SECONDS)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


@dataclass(slots=True)
class AsyncHTTPProxy:
    server: asyncio.AbstractServer
    base_url: str
    requests: list[ProxyRequest] = field(default_factory=list)

    async def close(self) -> None:
        self.server.close()
        await self.server.wait_closed()


class SyncHTTPProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._write_response()

    def do_POST(self) -> None:
        self._write_response()

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write_response(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else b""
        request = ProxyRequest(
            request_line=self.requestline,
            headers={name.lower(): self.headers.get_all(name, []) for name in self.headers},
            body=body,
        )
        self.server.proxy.append(request)  # type: ignore[attr-defined]

        if _target_path(self.path) == "/invalid-proxy-response":
            self.wfile.write(b"not an http response\r\n\r\n")
            return

        if _target_path(self.path) == PROXY_REDIRECT_PATH:
            self._write_redirect_response()
            return

        if _target_path(self.path) == PROXY_STREAM_EARLY_CLOSE_PATH:
            self._write_chunked_stream_response()
            return

        payload = _proxy_payload(request)
        self.send_response(OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def _write_redirect_response(self) -> None:
        self.send_response(FOUND)
        self.send_header("location", _target_query_value(self.path, PROXY_REDIRECT_LOCATION_PARAM))
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()

    def _write_chunked_stream_response(self) -> None:
        self.send_response(OK)
        self.send_header("content-type", "application/octet-stream")
        self.send_header("transfer-encoding", "chunked")
        self.send_header("connection", "close")
        self.end_headers()
        with suppress(OSError):
            for _index in range(PROXY_STREAM_CHUNKS):
                self.wfile.write(_chunk_frame(PROXY_STREAM_CHUNK))
                self.wfile.flush()
                self.server.proxy.wait_between_stream_chunks()  # type: ignore[attr-defined]
            self.wfile.write(b"0\r\n\r\n")


@pytest.fixture
def sync_http_proxy() -> Iterator[SyncHTTPProxy]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SyncHTTPProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    proxy = SyncHTTPProxy(server=server, thread=thread, base_url=f"http://{host}:{port}")
    server.proxy = proxy  # type: ignore[attr-defined]
    try:
        yield proxy
    finally:
        proxy.close()


@pytest.fixture
async def async_http_proxy() -> AsyncIterator[AsyncHTTPProxy]:
    proxy: AsyncHTTPProxy | None = None

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head, body = await _read_request(reader)
            request = ProxyRequest(
                request_line=head.splitlines()[0],
                headers=_headers_from_head(head),
                body=body,
            )
            if proxy is None:
                msg = "async proxy fixture was not initialized"
                raise RuntimeError(msg)
            proxy.requests.append(request)
            if _target_path(_request_target(request)) == PROXY_STREAM_EARLY_CLOSE_PATH:
                await _write_async_chunked_stream_response(writer)
            else:
                writer.write(_raw_proxy_response(request))
                await writer.drain()
        finally:
            writer.close()
            with suppress(asyncio.CancelledError, OSError):
                await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()
    proxy = AsyncHTTPProxy(server=server, base_url=f"http://{host}:{port}")
    try:
        yield proxy
    finally:
        await proxy.close()


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    head = (await reader.readuntil(b"\r\n\r\n")).decode("iso-8859-1")
    length = int(_headers_from_head(head).get("content-length", ["0"])[0])
    body = await reader.readexactly(length) if length else b""
    return head, body


def _headers_from_head(head: str) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for line in head.splitlines()[1:]:
        name, separator, value = line.partition(":")
        if separator:
            headers.setdefault(name.lower(), []).append(value.strip())
    return headers


def _raw_proxy_response(request: ProxyRequest) -> bytes:
    target = _request_target(request)
    if _target_path(target) == PROXY_REDIRECT_PATH:
        return raw_response(
            FOUND,
            "Found",
            [
                ("location", _target_query_value(target, PROXY_REDIRECT_LOCATION_PARAM)),
                ("content-length", "0"),
                ("connection", "close"),
            ],
        )

    return raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(_proxy_payload(request)))),
            ("connection", "close"),
        ],
        _proxy_payload(request),
    )


def _proxy_payload(request: ProxyRequest) -> bytes:
    return json.dumps(
        {
            "request_line": request.request_line,
            "headers": request.headers,
            "body": request.body.decode(),
        },
    ).encode()


async def _write_async_chunked_stream_response(writer: asyncio.StreamWriter) -> None:
    writer.write(
        raw_response(
            OK,
            "OK",
            [
                ("content-type", "application/octet-stream"),
                ("transfer-encoding", "chunked"),
                ("connection", "close"),
            ],
        ),
    )
    await writer.drain()
    with suppress(OSError):
        for _index in range(PROXY_STREAM_CHUNKS):
            writer.write(_chunk_frame(PROXY_STREAM_CHUNK))
            await writer.drain()
            await asyncio.sleep(PROXY_STREAM_CHUNK_DELAY_SECONDS)
        writer.write(b"0\r\n\r\n")
        await writer.drain()


def _request_target(request: ProxyRequest) -> str:
    return request.request_line.split()[1]


def _target_path(target: str) -> str:
    return urlsplit(target).path


def _target_query_value(target: str, name: str) -> str:
    prefix = f"{name}="
    for query_field in urlsplit(target).query.split("&"):
        if query_field.startswith(prefix):
            return query_field.removeprefix(prefix)
    msg = f"proxy redirect target is missing {name!r} query parameter"
    raise AssertionError(msg)


def _chunk_frame(chunk: bytes) -> bytes:
    return f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n"
