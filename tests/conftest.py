import asyncio
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK


REDIRECT_PATH_PARTS = 2
REDIRECT_TO_STATUS_PATH_PARTS = 3
STATUS_PATH_PARTS = 2
ECHO_HEADERS_PATH = "/headers/echo"
REPEATED_HEADERS_PATH = "/headers/repeated"
TEXT_PATH = "/text"


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


def _header_values(headers: str, name: str) -> list[str]:
    values: list[str] = []
    for line in headers.splitlines()[1:]:
        header_name, separator, value = line.partition(":")
        if separator and header_name.lower() == name:
            values.append(value.strip())
    return values


def _headers_payload(values: list[str]) -> bytes:
    return json.dumps({"x-repeat": values}).encode()


def _redirect_status(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == REDIRECT_PATH_PARTS and parts[0] == "redirect":
        return int(parts[1])
    return None


def _redirect_to_status(path: str) -> tuple[int, int] | None:
    parts = path.strip("/").split("/")
    if len(parts) == REDIRECT_TO_STATUS_PATH_PARTS and parts[0] == "redirect-to-status":
        return int(parts[1]), int(parts[2])
    return None


def _status_code(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == STATUS_PATH_PARTS and parts[0] == "status":
        return int(parts[1])
    return None


def _reason_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Status"


def _raw_response(
    status_code: int,
    reason: str,
    headers: list[tuple[str, str]],
    content: bytes = b"",
) -> bytes:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
    return f"HTTP/1.1 {status_code} {reason}\r\n{header_lines}\r\n".encode() + content


def _raw_empty_response(status_code: int, reason: str, headers: list[tuple[str, str]]) -> bytes:
    return _raw_response(
        status_code,
        reason,
        [*headers, ("content-length", "0"), ("connection", "close")],
    )


def _raw_redirect_to_status_response(path: str) -> bytes | None:
    redirect_to_status = _redirect_to_status(path)
    if redirect_to_status is None:
        return None

    redirect_status, final_status = redirect_to_status
    return _raw_empty_response(redirect_status, "Redirect", [("location", f"/status/{final_status}")])


def _raw_redirect_response(path: str) -> bytes | None:
    redirect_status = _redirect_status(path)
    if redirect_status is not None:
        return _raw_empty_response(redirect_status, "Redirect", [("location", "/final")])
    if path == "/loop":
        return _raw_empty_response(FOUND, "Redirect", [("location", "/loop")])
    return None


def _raw_status_response(path: str) -> bytes | None:
    status_code = _status_code(path)
    if status_code is None:
        return None

    return _raw_empty_response(status_code, _reason_phrase(status_code), [])


def _raw_text_response(path: str) -> bytes | None:
    if path != TEXT_PATH:
        return None

    content = b"Latin-1: \xe9"
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "text/plain; charset=iso-8859-1"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _raw_repeated_headers_response(path: str) -> bytes | None:
    if path != REPEATED_HEADERS_PATH:
        return None

    return _raw_empty_response(
        OK,
        "OK",
        [
            ("set-cookie", "first=1"),
            ("set-cookie", "second=2"),
            ("x-trace", "one"),
            ("x-trace", "two"),
        ],
    )


def _raw_echo_headers_response(path: str, headers: str) -> bytes | None:
    if path != ECHO_HEADERS_PATH:
        return None

    payload = _headers_payload(_header_values(headers, "x-repeat"))
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(payload))),
            ("connection", "close"),
        ],
        payload,
    )


def _raw_json_response(*, method: str, request_line: str, body: bytes) -> bytes:
    payload = _json_payload(request_line=request_line, body=body)
    content = b"" if method == "HEAD" else payload
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _raw_http_server_response(headers: str, body: bytes) -> bytes:
    request_line = headers.splitlines()[0]
    method, target, _version = request_line.split()
    path = urlsplit(target).path
    response = (
        _raw_redirect_to_status_response(path)
        or _raw_redirect_response(path)
        or _raw_status_response(path)
        or _raw_text_response(path)
        or _raw_repeated_headers_response(path)
        or _raw_echo_headers_response(path, headers)
    )
    return response or _raw_json_response(method=method, request_line=request_line, body=body)


@pytest.fixture
async def http_server() -> AsyncIterator[str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers, body = await _read_request(reader)
        writer.write(_raw_http_server_response(headers, body))
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


class SyncHTTPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._write_response()

    def do_HEAD(self) -> None:
        self._write_response()

    def do_POST(self) -> None:
        self._write_response()

    def do_PUT(self) -> None:
        self._write_response()

    def do_PATCH(self) -> None:
        self._write_response()

    def do_DELETE(self) -> None:
        self._write_response()

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write_response(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path

        if self._write_redirect_to_status(path):
            return
        if self._write_redirect(path):
            return
        if self._write_status(path):
            return
        if self._write_text(path):
            return
        if self._write_repeated_headers(path):
            return
        if self._write_echo_headers(path):
            return

        self._write_json(body)

    def _write_redirect_to_status(self, path: str) -> bool:
        redirect_to_status = _redirect_to_status(path)
        if redirect_to_status is None:
            return False

        redirect_status, final_status = redirect_to_status
        self._write_redirect_response(redirect_status, f"/status/{final_status}")
        return True

    def _write_redirect(self, path: str) -> bool:
        redirect_status = _redirect_status(path)
        if redirect_status is not None:
            self._write_redirect_response(redirect_status, "/final")
            return True
        if path == "/loop":
            self._write_redirect_response(FOUND, "/loop")
            return True
        return False

    def _write_redirect_response(self, status_code: int, location: str) -> None:
        self.send_response(status_code)
        self.send_header("location", location)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()

    def _write_status(self, path: str) -> bool:
        status_code = _status_code(path)
        if status_code is None:
            return False

        self.send_response(status_code)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()
        return True

    def _write_text(self, path: str) -> bool:
        if path != TEXT_PATH:
            return False

        content = b"Latin-1: \xe9"
        self.send_response(OK)
        self.send_header("content-type", "text/plain; charset=iso-8859-1")
        self.send_header("content-length", str(len(content)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(content)
        return True

    def _write_repeated_headers(self, path: str) -> bool:
        if path != REPEATED_HEADERS_PATH:
            return False

        self.send_response(OK)
        self.send_header("set-cookie", "first=1")
        self.send_header("set-cookie", "second=2")
        self.send_header("x-trace", "one")
        self.send_header("x-trace", "two")
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()
        return True

    def _write_echo_headers(self, path: str) -> bool:
        if path != ECHO_HEADERS_PATH:
            return False

        payload = _headers_payload(self.headers.get_all("x-repeat", []))
        self.send_response(OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(payload)
        return True

    def _write_json(self, body: bytes) -> None:
        payload = _json_payload(request_line=self.requestline, body=body)
        content = b"" if self.command == "HEAD" else payload
        self.send_response(OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(content)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(content)


@pytest.fixture
def sync_http_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SyncHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
