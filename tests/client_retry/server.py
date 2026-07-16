__all__ = ("RetryTestServer", "start_retry_test_server")

from dataclasses import dataclass
from socket import socket
from socketserver import BaseRequestHandler, ThreadingTCPServer
import threading
from typing import Self, cast
from urllib.parse import urlsplit

from foghttp.status_codes.server_error import SERVICE_UNAVAILABLE
from foghttp.status_codes.success import OK

from .constants import (
    ALWAYS_CLOSE_PATH,
    ALWAYS_STATUS_PATH,
    CLOSE_THEN_OK_PATH,
    EARLY_STATUS_THEN_OK_PATH,
    INCOMPLETE_RETRYABLE_RESPONSE_PATH,
    STATUS_THEN_OK_PATH,
)
from .models import RetryRequest, RetryServerSnapshot


HTTP_HEAD_END = b"\r\n\r\n"
HTTP_LINE_END = b"\r\n"
MAX_REQUEST_BODY_SIZE = 1024 * 1024
MAX_REQUEST_HEAD_SIZE = 64 * 1024
INVALID_CHUNK_DELIMITER = "invalid chunk delimiter"
INVALID_CHUNK_SIZE = "invalid chunk size"
INVALID_CONTENT_LENGTH = "invalid content-length"
INVALID_REQUEST_LINE = "invalid request line"
INCOMPLETE_RESPONSE_BODY = b"incomplete"
INCOMPLETE_RESPONSE_CONTENT_LENGTH = len(INCOMPLETE_RESPONSE_BODY) + 1
REQUEST_BODY_LIMIT_EXCEEDED = "request body exceeds test server limit"
REQUEST_HEAD_LIMIT_EXCEEDED = "request head exceeds test server limit"
SERVER_HOST = "127.0.0.1"
SERVER_JOIN_TIMEOUT = 1.0
SERVER_POLL_INTERVAL = 0.01
SOCKET_READ_SIZE = 4096
SOCKET_TIMEOUT = 2.0
UNEXPECTED_END_OF_REQUEST = "unexpected end of request"


@dataclass(slots=True)
class RetryTestServer:
    server: "RetryTCPServer"
    thread: threading.Thread

    @property
    def url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def snapshot(self) -> RetryServerSnapshot:
        return self.server.state.snapshot()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=SERVER_JOIN_TIMEOUT)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def start_retry_test_server() -> RetryTestServer:
    server = RetryTCPServer((SERVER_HOST, 0), RetryHTTPHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": SERVER_POLL_INTERVAL},
        daemon=True,
    )
    thread.start()
    return RetryTestServer(server=server, thread=thread)


class RetryTCPServer(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_type: type[BaseRequestHandler],
    ) -> None:
        self.state = RetryServerState()
        super().__init__(server_address, handler_type)

    def handle_error(self, _request: object, _client_address: object) -> None:
        return


class RetryHTTPHandler(BaseRequestHandler):
    def handle(self) -> None:
        connection = cast("socket", self.request)
        connection.settimeout(SOCKET_TIMEOUT)
        server = cast("RetryTCPServer", self.server)
        connection_id = server.state.register_connection()
        pending = b""

        while True:
            try:
                request_head, pending = _read_parsed_request_head(connection, pending)
            except (OSError, ValueError):
                break
            if request_head is None:
                break

            path = urlsplit(request_head.target).path
            if path == EARLY_STATUS_THEN_OK_PATH and server.state.record_first_request(
                RetryRequest(
                    path=path,
                    method=request_head.method,
                    body=b"",
                    connection_id=connection_id,
                ),
            ):
                response = _raw_response(
                    SERVICE_UNAVAILABLE,
                    "Service Unavailable",
                    b"retryable",
                    close=True,
                )
                connection.sendall(response)
                return

            try:
                body, pending = _read_request_body(connection, pending, request_head.headers)
            except (OSError, ValueError):
                return
            parsed = ParsedRequest(
                method=request_head.method,
                target=request_head.target,
                headers=request_head.headers,
                body=body,
            )
            attempt = server.state.record_request(
                RetryRequest(
                    path=path,
                    method=parsed.method,
                    body=parsed.body,
                    connection_id=connection_id,
                ),
            )
            if path == INCOMPLETE_RETRYABLE_RESPONSE_PATH:
                response = _raw_response(
                    SERVICE_UNAVAILABLE,
                    "Service Unavailable",
                    INCOMPLETE_RESPONSE_BODY,
                    close=True,
                    content_length=INCOMPLETE_RESPONSE_CONTENT_LENGTH,
                )
                connection.sendall(response)
                return
            if path == ALWAYS_CLOSE_PATH or (path == CLOSE_THEN_OK_PATH and attempt == 1):
                return

            if path == ALWAYS_STATUS_PATH or (path == STATUS_THEN_OK_PATH and attempt == 1):
                response = _raw_response(SERVICE_UNAVAILABLE, "Service Unavailable", b"retryable")
            else:
                response = _raw_response(OK, "OK", parsed.body or b"ok")
            connection.sendall(response)

            if _request_closes_connection(parsed.headers):
                return


class RetryServerState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_connection_id = 0
        self._requests: list[RetryRequest] = []

    def register_connection(self) -> int:
        with self._lock:
            self._next_connection_id += 1
            return self._next_connection_id

    def record_request(self, request: RetryRequest) -> int:
        with self._lock:
            self._requests.append(request)
            return sum(item.path == request.path for item in self._requests)

    def record_first_request(self, request: RetryRequest) -> bool:
        with self._lock:
            if any(item.path == request.path for item in self._requests):
                return False
            self._requests.append(request)
            return True

    def snapshot(self) -> RetryServerSnapshot:
        with self._lock:
            return RetryServerSnapshot(requests=tuple(self._requests))


@dataclass(frozen=True, slots=True)
class ParsedRequest:
    method: str
    target: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class ParsedRequestHead:
    method: str
    target: str
    headers: dict[str, str]


def _read_parsed_request_head(
    connection: socket,
    pending: bytes,
) -> tuple[ParsedRequestHead | None, bytes]:
    request_head, pending = _read_request_head(connection, pending)
    if request_head is None:
        return None, pending

    lines = request_head.decode("iso-8859-1").split("\r\n")
    try:
        method, target, _version = lines[0].split(maxsplit=2)
    except ValueError as error:
        raise ValueError(INVALID_REQUEST_LINE) from error
    headers = _parse_headers(lines[1:])
    return ParsedRequestHead(method=method, target=target, headers=headers), pending


def _read_request_head(connection: socket, pending: bytes) -> tuple[bytes | None, bytes]:
    while HTTP_HEAD_END not in pending:
        chunk = connection.recv(SOCKET_READ_SIZE)
        if not chunk:
            return None, pending
        pending += chunk
        if len(pending) > MAX_REQUEST_HEAD_SIZE:
            raise ValueError(REQUEST_HEAD_LIMIT_EXCEEDED)
    head, _separator, pending = pending.partition(HTTP_HEAD_END)
    return head, pending


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in lines:
        name, separator, value = line.partition(":")
        if separator:
            headers[name.strip().casefold()] = value.strip()
    return headers


def _read_request_body(
    connection: socket,
    pending: bytes,
    headers: dict[str, str],
) -> tuple[bytes, bytes]:
    transfer_encodings = {
        token.strip().casefold() for token in headers.get("transfer-encoding", "").split(",") if token.strip()
    }
    if "chunked" in transfer_encodings:
        return _read_chunked_body(connection, pending)

    raw_content_length = headers.get("content-length", "0")
    try:
        content_length = int(raw_content_length)
    except ValueError as error:
        raise ValueError(INVALID_CONTENT_LENGTH) from error
    if not 0 <= content_length <= MAX_REQUEST_BODY_SIZE:
        raise ValueError(REQUEST_BODY_LIMIT_EXCEEDED)
    return _read_exact(connection, pending, content_length)


def _read_chunked_body(connection: socket, pending: bytes) -> tuple[bytes, bytes]:
    body = bytearray()
    while True:
        size_line, pending = _read_line(connection, pending)
        try:
            size = int(size_line.split(b";", maxsplit=1)[0], 16)
        except ValueError as error:
            raise ValueError(INVALID_CHUNK_SIZE) from error
        if size == 0:
            return bytes(body), _consume_trailers(connection, pending)
        if len(body) + size > MAX_REQUEST_BODY_SIZE:
            raise ValueError(REQUEST_BODY_LIMIT_EXCEEDED)
        chunk, pending = _read_exact(connection, pending, size)
        line_end, pending = _read_exact(connection, pending, len(HTTP_LINE_END))
        if line_end != HTTP_LINE_END:
            raise ValueError(INVALID_CHUNK_DELIMITER)
        body.extend(chunk)


def _consume_trailers(connection: socket, pending: bytes) -> bytes:
    while True:
        line, pending = _read_line(connection, pending)
        if not line:
            return pending


def _read_line(connection: socket, pending: bytes) -> tuple[bytes, bytes]:
    while HTTP_LINE_END not in pending:
        chunk = connection.recv(SOCKET_READ_SIZE)
        if not chunk:
            raise ValueError(UNEXPECTED_END_OF_REQUEST)
        pending += chunk
    line, _separator, pending = pending.partition(HTTP_LINE_END)
    return line, pending


def _read_exact(connection: socket, pending: bytes, size: int) -> tuple[bytes, bytes]:
    while len(pending) < size:
        chunk = connection.recv(min(SOCKET_READ_SIZE, size - len(pending)))
        if not chunk:
            raise ValueError(UNEXPECTED_END_OF_REQUEST)
        pending += chunk
    return pending[:size], pending[size:]


def _request_closes_connection(headers: dict[str, str]) -> bool:
    tokens = {token.strip().casefold() for token in headers.get("connection", "").split(",")}
    return "close" in tokens


def _raw_response(
    status_code: int,
    reason: str,
    content: bytes,
    *,
    close: bool = False,
    content_length: int | None = None,
) -> bytes:
    connection = "close" if close else "keep-alive"
    declared_content_length = len(content) if content_length is None else content_length
    return (
        f"HTTP/1.1 {status_code} {reason}\r\n"
        f"content-length: {declared_content_length}\r\n"
        "content-type: application/octet-stream\r\n"
        f"connection: {connection}\r\n"
        "\r\n"
    ).encode() + content
