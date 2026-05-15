import asyncio
from collections.abc import AsyncIterator, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK


REDIRECT_PATH_PARTS = 2
REDIRECT_TO_STATUS_PATH_PARTS = 3
STATUS_PATH_PARTS = 2
ECHO_HEADERS_PATH = "/headers/echo"
REPEATED_HEADERS_PATH = "/headers/repeated"
REDIRECT_TO_LOCATION_PATH = "/redirect-to-location"
SECURITY_HEADERS_PATH = "/headers/security"
TEXT_PATH = "/text"
BYTES_PATH_PARTS = 2
UNKNOWN_SIZE_BYTES_ROUTE = "unknown-size-bytes"


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


def _security_headers_payload(*, headers: dict[str, list[str]], request_line: str, body: bytes) -> bytes:
    return json.dumps(
        {
            "headers": headers,
            "request_line": request_line,
            "body": body.decode(),
        },
    ).encode()


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


def _redirect_to_location(path: str, query: str) -> tuple[int, str] | None:
    if path != REDIRECT_TO_LOCATION_PATH:
        return None

    params = parse_qs(query, keep_blank_values=True)
    status_values = params.get("status", [])
    location_values = params.get("location", [])
    if not status_values or not location_values:
        return None
    return int(status_values[0]), location_values[0]


def _status_code(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == STATUS_PATH_PARTS and parts[0] == "status":
        return int(parts[1])
    return None


def _bytes_response_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == BYTES_PATH_PARTS and parts[0] == "bytes":
        return int(parts[1])
    return None


def _unknown_size_bytes_response_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) == BYTES_PATH_PARTS and parts[0] == UNKNOWN_SIZE_BYTES_ROUTE:
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


def _raw_redirect_to_location_response(path: str, query: str) -> bytes | None:
    redirect_to_location = _redirect_to_location(path, query)
    if redirect_to_location is None:
        return None

    redirect_status, location = redirect_to_location
    return _raw_empty_response(redirect_status, "Redirect", [("location", location)])


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


def _raw_bytes_response(path: str) -> bytes | None:
    response_size = _bytes_response_size(path)
    if response_size is None:
        return None

    content = b"x" * response_size
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/octet-stream"),
            ("content-length", str(len(content))),
            ("connection", "close"),
        ],
        content,
    )


def _raw_unknown_size_bytes_response(path: str) -> bytes | None:
    response_size = _unknown_size_bytes_response_size(path)
    if response_size is None:
        return None

    content = b"x" * response_size
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/octet-stream"),
            ("connection", "close"),
        ],
        content,
    )


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


def _security_headers_from_raw(headers: str) -> dict[str, list[str]]:
    return {
        name: _header_values(headers, name)
        for name in (
            "accept",
            "authorization",
            "content-encoding",
            "content-length",
            "content-type",
            "cookie",
            "host",
            "origin",
            "proxy-authorization",
            "referer",
            "transfer-encoding",
        )
    }


def _raw_security_headers_response(path: str, headers: str, body: bytes) -> bytes | None:
    if path != SECURITY_HEADERS_PATH:
        return None

    payload = _security_headers_payload(
        headers=_security_headers_from_raw(headers),
        request_line=headers.splitlines()[0],
        body=body,
    )
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
    target_parts = urlsplit(target)
    path = target_parts.path
    response = (
        _raw_redirect_to_location_response(path, target_parts.query)
        or _raw_redirect_to_status_response(path)
        or _raw_redirect_response(path)
        or _raw_status_response(path)
        or _raw_bytes_response(path)
        or _raw_unknown_size_bytes_response(path)
        or _raw_text_response(path)
        or _raw_repeated_headers_response(path)
        or _raw_echo_headers_response(path, headers)
        or _raw_security_headers_response(path, headers, body)
    )
    return response or _raw_json_response(method=method, request_line=request_line, body=body)


async def _start_async_http_server() -> tuple[Any, str]:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers, body = await _read_request(reader)
        writer.write(_raw_http_server_response(headers, body))
        await writer.drain()
        writer.close()
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

        handled = any(
            handler()
            for handler in (
                self._write_redirect_to_location,
                lambda: self._write_redirect_to_status(path),
                lambda: self._write_redirect(path),
                lambda: self._write_status(path),
                lambda: self._write_bytes(path),
                lambda: self._write_unknown_size_bytes(path),
                lambda: self._write_text(path),
                lambda: self._write_repeated_headers(path),
                lambda: self._write_echo_headers(path),
                lambda: self._write_security_headers(path, body),
            )
        )
        if handled:
            return

        self._write_json(body)

    def _write_redirect_to_location(self) -> bool:
        target = urlsplit(self.path)
        redirect_to_location = _redirect_to_location(target.path, target.query)
        if redirect_to_location is None:
            return False

        redirect_status, location = redirect_to_location
        self._write_redirect_response(redirect_status, location)
        return True

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

    def _write_bytes(self, path: str) -> bool:
        response_size = _bytes_response_size(path)
        if response_size is None:
            return False

        content = b"x" * response_size
        self.send_response(OK)
        self.send_header("content-type", "application/octet-stream")
        self.send_header("content-length", str(len(content)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(content)
        return True

    def _write_unknown_size_bytes(self, path: str) -> bool:
        response_size = _unknown_size_bytes_response_size(path)
        if response_size is None:
            return False

        content = b"x" * response_size
        self.close_connection = True
        self.send_response(OK)
        self.send_header("content-type", "application/octet-stream")
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(content)
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

    def _write_security_headers(self, path: str, body: bytes) -> bool:
        if path != SECURITY_HEADERS_PATH:
            return False

        headers = {
            name: self.headers.get_all(name, [])
            for name in (
                "accept",
                "authorization",
                "content-encoding",
                "content-length",
                "content-type",
                "cookie",
                "host",
                "origin",
                "proxy-authorization",
                "referer",
                "transfer-encoding",
            )
        }
        payload = _security_headers_payload(
            headers=headers,
            request_line=self.requestline,
            body=body,
        )
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


def _start_sync_http_server() -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SyncHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"


@pytest.fixture
def sync_http_server() -> Iterator[str]:
    server, thread, base_url = _start_sync_http_server()
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


@pytest.fixture
def secondary_sync_http_server() -> Iterator[str]:
    server, thread, base_url = _start_sync_http_server()
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
