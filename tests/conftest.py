import asyncio
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK


REDIRECT_PATH_PARTS = 2


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, bytes]:
    head = await reader.readuntil(b"\r\n\r\n")
    headers = head.decode("iso-8859-1")
    length = 0
    for line in headers.split("\r\n"):
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            length = int(value.strip())
    body = await reader.readexactly(length) if length else b""
    return headers, body


def _json_payload(*, request_line: str, body: bytes) -> bytes:
    return json.dumps(
        {
            "request_line": request_line,
            "body": body.decode(),
        },
    ).encode()


def _redirect_status(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == REDIRECT_PATH_PARTS and parts[0] == "redirect":
        return int(parts[1])
    return None


@pytest.fixture
async def http_server() -> AsyncIterator[str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers, body = await _read_request(reader)
        request_line = headers.splitlines()[0]
        method, target, _version = request_line.split()
        path = urlsplit(target).path
        redirect_status = _redirect_status(path)
        if redirect_status is not None:
            writer.write(
                f"HTTP/1.1 {redirect_status} Redirect\r\n".encode()
                + b"location: /final\r\n"
                + b"content-length: 0\r\n"
                + b"connection: close\r\n\r\n",
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return
        if path == "/loop":
            writer.write(
                f"HTTP/1.1 {FOUND} Redirect\r\n"
                "location: /loop\r\n"
                "content-length: 0\r\n"
                "connection: close\r\n\r\n".encode(),
            )
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        payload = _json_payload(request_line=request_line, body=body)
        content = b"" if method == "HEAD" else payload
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"content-type: application/json\r\n"
            + f"content-length: {len(content)}\r\n".encode()
            + b"connection: close\r\n\r\n"
            + content,
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        host, port = server.sockets[0].getsockname()
        yield f"http://{host}:{port}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def sync_http_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._write_response()

        def do_HEAD(self) -> None:
            self._write_response()

        def do_POST(self) -> None:
            self._write_response()

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _write_response(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length) if length else b""

            redirect_status = _redirect_status(urlsplit(self.path).path)
            if redirect_status is not None:
                self.send_response(redirect_status)
                self.send_header("location", "/final")
                self.send_header("content-length", "0")
                self.send_header("connection", "close")
                self.end_headers()
                return
            if urlsplit(self.path).path == "/loop":
                self.send_response(FOUND)
                self.send_header("location", "/loop")
                self.send_header("content-length", "0")
                self.send_header("connection", "close")
                self.end_headers()
                return

            payload = _json_payload(request_line=self.requestline, body=body)
            content = b"" if self.command == "HEAD" else payload
            self.send_response(OK)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(content)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
