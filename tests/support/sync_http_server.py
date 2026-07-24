__all__ = ("secondary_sync_http_server", "sync_http_server")

from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any, BinaryIO
from urllib.parse import urlsplit

import pytest

from foghttp.methods import HEAD
from foghttp.status_codes.redirect import FOUND
from foghttp.status_codes.success import OK
from tests.http_body_scenarios import write_sync_body_safety_response
from tests.support.http_routes import (
    ECHO_HEADERS_PATH,
    OBS_TEXT_HEADERS_PATH,
    REPEATED_HEADERS_PATH,
    SECURITY_HEADERS_PATH,
    TEXT_PATH,
    bytes_response_size,
    cookie_response,
    redirect_status,
    redirect_to_location,
    redirect_to_status,
    status_code,
    unknown_size_bytes_response_size,
)
from tests.support.raw_responses import (
    SECURITY_HEADER_NAMES,
    headers_payload,
    json_payload,
    security_headers_payload,
)


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

    def do_QUERY(self) -> None:
        self._write_response()

    def do_PATCH(self) -> None:
        self._write_response()

    def do_DELETE(self) -> None:
        self._write_response()

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _write_response(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        if self.headers.get("transfer-encoding", "").lower() == "chunked":
            body = _read_chunked_body(self.rfile)
        else:
            body = self.rfile.read(length) if length else b""
        path = urlsplit(self.path).path

        handled = any(
            handler()
            for handler in (
                self._write_cookie_response,
                self._write_redirect_to_location,
                lambda: self._write_redirect_to_status(path),
                lambda: self._write_redirect(path),
                lambda: self._write_status(path),
                lambda: write_sync_body_safety_response(self, path),
                lambda: self._write_bytes(path),
                lambda: self._write_unknown_size_bytes(path),
                lambda: self._write_text(path),
                lambda: self._write_repeated_headers(path),
                lambda: self._write_obs_text_headers(path),
                lambda: self._write_echo_headers(path),
                lambda: self._write_security_headers(path, body),
            )
        )
        if handled:
            return

        self._write_json(body)

    def _write_cookie_response(self) -> bool:
        target = urlsplit(self.path)
        response = cookie_response(
            target.path,
            target.query,
            self.headers.get_all("cookie", []),
        )
        if response is None:
            return False
        status_code, headers, content = response
        self.send_response(status_code)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("content-length", str(len(content)))
        self.send_header("connection", "close")
        self.end_headers()
        self.wfile.write(content)
        return True

    def _write_redirect_to_location(self) -> bool:
        target = urlsplit(self.path)
        redirect = redirect_to_location(target.path, target.query)
        if redirect is None:
            return False

        redirect_code, location = redirect
        self._write_redirect_response(redirect_code, location)
        return True

    def _write_redirect_to_status(self, path: str) -> bool:
        redirect = redirect_to_status(path)
        if redirect is None:
            return False

        redirect_code, final_status = redirect
        self._write_redirect_response(redirect_code, f"/status/{final_status}")
        return True

    def _write_redirect(self, path: str) -> bool:
        redirect_code = redirect_status(path)
        if redirect_code is not None:
            self._write_redirect_response(redirect_code, "/final")
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
        code = status_code(path)
        if code is None:
            return False

        self.send_response(code)
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()
        return True

    def _write_bytes(self, path: str) -> bool:
        response_size = bytes_response_size(path)
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
        response_size = unknown_size_bytes_response_size(path)
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

    def _write_obs_text_headers(self, path: str) -> bool:
        if path != OBS_TEXT_HEADERS_PATH:
            return False

        self.send_response(OK)
        self.send_header("x-obs-text", "value-\xe9")
        self.send_header("x-repeat", "ascii")
        self.send_header("x-repeat", "repeat-\xe9")
        self.send_header("content-length", "0")
        self.send_header("connection", "close")
        self.end_headers()
        return True

    def _write_echo_headers(self, path: str) -> bool:
        if path != ECHO_HEADERS_PATH:
            return False

        payload = headers_payload(self.headers.get_all("x-repeat", []))
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

        headers = {name: self.headers.get_all(name, []) for name in SECURITY_HEADER_NAMES}
        payload = security_headers_payload(
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
        payload = json_payload(request_line=self.requestline, body=body)
        content = b"" if self.command == HEAD else payload
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


def _read_chunked_body(reader: BinaryIO) -> bytes:
    body = bytearray()
    while True:
        size_line = reader.readline()
        size = int(size_line.split(b";", maxsplit=1)[0].strip(), 16)
        if size == 0:
            _read_trailers(reader)
            return bytes(body)
        body.extend(reader.read(size))
        reader.read(2)


def _read_trailers(reader: BinaryIO) -> None:
    while True:
        line = reader.readline()
        if line in (b"\r\n", b""):
            return


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
