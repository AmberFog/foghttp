__all__ = (
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

from foghttp.status_codes.success import OK
from tests.support.raw_responses import raw_response


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

    @property
    def requests(self) -> list[ProxyRequest]:
        with self._lock:
            return list(self._requests)

    def append(self, request: ProxyRequest) -> None:
        with self._lock:
            self._requests.append(request)

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

        payload = _proxy_payload(request)
        self.send_response(OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(payload)


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


def _target_path(target: str) -> str:
    return urlsplit(target).path
