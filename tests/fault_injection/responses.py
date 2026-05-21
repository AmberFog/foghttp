__all__ = (
    "write_empty_response",
    "write_fault_response",
)

import json
from socket import socket
import time

from foghttp.status_codes.success import OK

from .constants import (
    ABRUPT_BEFORE_HEADERS_PATH,
    ABRUPT_DURING_BODY_PATH,
    CONNECTION_ID_KEY,
    DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH,
    FAULT_DELAY,
    HEALTHY_BODY,
    HEALTHY_PATH,
    INCOMPLETE_BODY_PATH,
    PARTIAL_BODY,
    REQUEST_INDEX_KEY,
    SLOW_BODY_PATH,
    SLOW_HEADERS_PATH,
)


DELAYED_EOF_PATH_PARTS = 2


def write_fault_response(
    connection: socket,
    *,
    path: str,
    connection_id: int,
    request_index: int,
    close: bool,
) -> bool:
    delayed_eof_size = _delayed_eof_unknown_size(path)
    closes_connection = True
    if path == ABRUPT_BEFORE_HEADERS_PATH:
        # Returning without bytes simulates an upstream closing before headers.
        pass
    elif path == ABRUPT_DURING_BODY_PATH:
        connection.sendall(_raw_known_size_headers(len(PARTIAL_BODY) * 2, close=True) + PARTIAL_BODY)
    elif path == INCOMPLETE_BODY_PATH:
        connection.sendall(_raw_known_size_headers(len(PARTIAL_BODY) * 2, close=True) + PARTIAL_BODY)
        time.sleep(FAULT_DELAY)
    elif path == SLOW_HEADERS_PATH:
        time.sleep(FAULT_DELAY)
        connection.sendall(_raw_healthy_response(connection_id, request_index, close=close))
        closes_connection = close
    elif path == SLOW_BODY_PATH:
        connection.sendall(_raw_known_size_headers(len(HEALTHY_BODY), close=close))
        time.sleep(FAULT_DELAY)
        connection.sendall(HEALTHY_BODY)
        closes_connection = close
    elif delayed_eof_size is not None:
        _write_delayed_eof_unknown_size_body(connection, delayed_eof_size)
    elif path == HEALTHY_PATH:
        connection.sendall(_raw_healthy_response(connection_id, request_index, close=close))
        closes_connection = close
    else:
        closes_connection = False
    return closes_connection


def write_empty_response(connection: socket, status_code: int, reason: str, *, close: bool) -> None:
    connection.sendall(
        _raw_response(
            status_code,
            reason,
            [
                ("content-length", "0"),
                ("connection", "close" if close else "keep-alive"),
            ],
        ),
    )


def _write_delayed_eof_unknown_size_body(connection: socket, response_size: int) -> None:
    # Without content-length the body remains incomplete until EOF; the delayed
    # close makes aggregate buffered-budget overlap deterministic under review.
    connection.sendall(
        _raw_headers(
            [
                ("content-type", "application/octet-stream"),
                ("connection", "close"),
            ],
        ),
    )
    connection.sendall(b"x" * response_size)
    time.sleep(FAULT_DELAY)


def _delayed_eof_unknown_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) != DELAYED_EOF_PATH_PARTS:
        return None

    route, response_size = parts
    if route != DELAYED_EOF_UNKNOWN_SIZE_BODY_PATH.strip("/"):
        return None
    return int(response_size)


def _raw_healthy_response(connection_id: int, request_index: int, *, close: bool) -> bytes:
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


def _raw_known_size_headers(content_length: int, *, close: bool) -> bytes:
    return _raw_headers(
        [
            ("content-type", "application/octet-stream"),
            ("content-length", str(content_length)),
            ("connection", "close" if close else "keep-alive"),
        ],
    )


def _raw_headers(headers: list[tuple[str, str]]) -> bytes:
    return _raw_response(OK, "OK", headers)


def _raw_response(
    status_code: int,
    reason: str,
    headers: list[tuple[str, str]],
    content: bytes = b"",
) -> bytes:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
    return f"HTTP/1.1 {status_code} {reason}\r\n{header_lines}\r\n".encode() + content
