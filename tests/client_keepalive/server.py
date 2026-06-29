__all__ = (
    "KeepAliveServer",
    "start_keepalive_server",
)

from dataclasses import dataclass
import json
from socket import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from typing import Self, cast
from urllib.parse import urlsplit

from foghttp.status_codes.client_error import BAD_REQUEST, NOT_FOUND
from foghttp.status_codes.success import OK

from .constants import CONNECTION_ID_KEY, KEEPALIVE_PATH, REQUEST_INDEX_KEY
from .models import KeepAliveSnapshot


HTTP_HEAD_END = b"\r\n\r\n"
SERVER_HOST = "127.0.0.1"
SERVER_JOIN_TIMEOUT = 1.0
SOCKET_READ_SIZE = 4096
SOCKET_TIMEOUT = 1.0


@dataclass(slots=True)
class KeepAliveServer:
    server: "KeepAliveTCPServer"
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def snapshot(self) -> KeepAliveSnapshot:
        return self.server.state.snapshot()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def start_keepalive_server() -> KeepAliveServer:
    state = KeepAliveState()
    server = KeepAliveTCPServer((SERVER_HOST, 0), KeepAliveHTTPHandler)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return KeepAliveServer(server=server, thread=thread)


class KeepAliveTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    state: "KeepAliveState"


class KeepAliveHTTPHandler(BaseRequestHandler):
    def handle(self) -> None:
        connection = cast("socket", self.request)
        connection.settimeout(SOCKET_TIMEOUT)
        server = cast("KeepAliveTCPServer", self.server)
        connection_id = server.state.register_connection()
        pending = b""

        while True:
            request_head, pending = _read_request_head(connection, pending)
            if request_head is None:
                return

            request = _parse_request(request_head)
            if request is None:
                connection.sendall(_raw_empty_response(BAD_REQUEST, "Bad Request", close=True))
                return
            pending = _discard_request_body(connection, pending, request.content_length)
            if pending is None:
                return

            close_after_response = _request_closes_connection(request.headers)
            request_index = server.state.record_request(connection_id)
            if urlsplit(request.target).path != KEEPALIVE_PATH:
                connection.sendall(_raw_empty_response(NOT_FOUND, "Not Found", close=True))
                return

            connection.sendall(
                _raw_keepalive_response(
                    connection_id=connection_id,
                    request_index=request_index,
                    close=close_after_response,
                ),
            )
            if close_after_response:
                return


class KeepAliveState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_connection_id = 0
        self._requests_by_connection: dict[int, int] = {}

    def register_connection(self) -> int:
        with self._lock:
            self._next_connection_id += 1
            connection_id = self._next_connection_id
            self._requests_by_connection[connection_id] = 0
            return connection_id

    def record_request(self, connection_id: int) -> int:
        with self._lock:
            request_index = self._requests_by_connection[connection_id] + 1
            self._requests_by_connection[connection_id] = request_index
            return request_index

    def snapshot(self) -> KeepAliveSnapshot:
        with self._lock:
            requests_by_connection = dict(self._requests_by_connection)
        return KeepAliveSnapshot(
            connection_count=len(requests_by_connection),
            request_count=sum(requests_by_connection.values()),
            requests_by_connection=requests_by_connection,
        )


@dataclass(frozen=True, slots=True)
class ParsedRequest:
    target: str
    headers: dict[str, str]
    content_length: int


def _read_request_head(connection: socket, pending: bytes) -> tuple[bytes | None, bytes]:
    while HTTP_HEAD_END not in pending:
        try:
            chunk = connection.recv(SOCKET_READ_SIZE)
        except (OSError, TimeoutError):
            return None, pending
        if not chunk:
            return None, pending
        pending += chunk

    request_head, separator, rest = pending.partition(HTTP_HEAD_END)
    return request_head + separator, rest


def _parse_request(request_head: bytes) -> ParsedRequest | None:
    lines = request_head.decode("iso-8859-1").split("\r\n")
    request_line = lines[0]
    try:
        _method, target, _version = request_line.split(maxsplit=2)
    except ValueError:
        return None

    headers = _parse_headers(lines[1:])
    content_length = _content_length(headers)
    if content_length is None:
        return None

    return ParsedRequest(
        target=target,
        headers=headers,
        content_length=content_length,
    )


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().casefold()] = value.strip()
    return headers


def _content_length(headers: dict[str, str]) -> int | None:
    raw_value = headers.get("content-length", "0")
    try:
        value = int(raw_value)
    except ValueError:
        return None
    return None if value < 0 else value


def _discard_request_body(
    connection: socket,
    pending: bytes,
    content_length: int,
) -> bytes | None:
    remaining = content_length - len(pending)
    while remaining > 0:
        try:
            chunk = connection.recv(min(SOCKET_READ_SIZE, remaining))
        except (OSError, TimeoutError):
            return None
        if not chunk:
            return None
        pending += chunk
        remaining -= len(chunk)
    return pending[content_length:]


def _request_closes_connection(headers: dict[str, str]) -> bool:
    tokens = {token.strip().casefold() for token in headers.get("connection", "").split(",")}
    return "close" in tokens


def _raw_keepalive_response(*, connection_id: int, request_index: int, close: bool) -> bytes:
    content = json.dumps(
        {
            CONNECTION_ID_KEY: connection_id,
            REQUEST_INDEX_KEY: request_index,
        },
    ).encode()
    return _raw_response(
        OK,
        "OK",
        [
            ("content-type", "application/json"),
            ("content-length", str(len(content))),
            ("connection", "close" if close else "keep-alive"),
        ],
        content,
    )


def _raw_empty_response(status_code: int, reason: str, *, close: bool) -> bytes:
    return _raw_response(
        status_code,
        reason,
        [
            ("content-length", "0"),
            ("connection", "close" if close else "keep-alive"),
        ],
    )


def _raw_response(
    status_code: int,
    reason: str,
    headers: list[tuple[str, str]],
    content: bytes = b"",
) -> bytes:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
    return f"HTTP/1.1 {status_code} {reason}\r\n{header_lines}\r\n".encode() + content
