__all__ = (
    "DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH",
    "INCOMPLETE_CHUNKED_BODY_PATH",
    "SLOW_BODY_PATH",
    "TOO_LARGE_SIZE_HINT_PATH",
    "raw_too_large_size_hint_response",
    "write_async_body_safety_response",
    "write_sync_body_safety_response",
)

import asyncio
from contextlib import suppress
from http.server import BaseHTTPRequestHandler
import time

from foghttp.limits import DEFAULT_MAX_RESPONSE_BODY_SIZE
from foghttp.status_codes.success import OK


BODY_RESPONSE_DELAY = 0.25
DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH = "/delayed-eof-unknown-size-bytes"
INCOMPLETE_CHUNKED_BODY_PATH = "/incomplete-chunked-body"
SLOW_BODY_PATH = "/slow-body"
TOO_LARGE_SIZE_HINT_PATH = "/too-large-size-hint"
DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH_PARTS = 2


def raw_too_large_size_hint_response(path: str) -> bytes | None:
    if path != TOO_LARGE_SIZE_HINT_PATH:
        return None

    return _raw_response(
        [
            ("content-type", "application/octet-stream"),
            ("content-length", str(DEFAULT_MAX_RESPONSE_BODY_SIZE + 1)),
            ("connection", "close"),
        ],
    )


async def write_async_body_safety_response(
    path: str,
    writer: asyncio.StreamWriter,
) -> bool:
    if path == SLOW_BODY_PATH:
        writer.write(
            _raw_response(
                [
                    ("content-type", "application/octet-stream"),
                    ("content-length", "1"),
                    ("connection", "close"),
                ],
            ),
        )
        await writer.drain()
        await asyncio.sleep(BODY_RESPONSE_DELAY)
        writer.write(b"x")
        await writer.drain()
        return True

    if path == INCOMPLETE_CHUNKED_BODY_PATH:
        writer.write(
            _raw_response(
                [
                    ("content-type", "application/octet-stream"),
                    ("transfer-encoding", "chunked"),
                    ("connection", "close"),
                ],
                b"1\r\nx\r\n",
            ),
        )
        await writer.drain()
        await asyncio.sleep(BODY_RESPONSE_DELAY)
        return True

    response_size = _delayed_eof_unknown_size_bytes_response_size(path)
    if response_size is not None:
        writer.write(
            _raw_response(
                [
                    ("content-type", "application/octet-stream"),
                    ("connection", "close"),
                ],
                b"x" * response_size,
            ),
        )
        await writer.drain()
        # Without content-length the body remains incomplete until EOF; delaying
        # close keeps concurrent buffered-body budget tests deterministic.
        await asyncio.sleep(BODY_RESPONSE_DELAY)
        return True

    return False


def write_sync_body_safety_response(
    handler: BaseHTTPRequestHandler,
    path: str,
) -> bool:
    return (
        _write_sync_too_large_size_hint(handler, path)
        or _write_sync_slow_body(handler, path)
        or _write_sync_incomplete_chunked_body(handler, path)
        or _write_sync_delayed_eof_unknown_size_bytes(handler, path)
    )


def _delayed_eof_unknown_size_bytes_response_size(path: str) -> int | None:
    parts = path.strip("/").split("/")
    if len(parts) != DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH_PARTS:
        return None

    route, response_size = parts
    if route != DELAYED_EOF_UNKNOWN_SIZE_BYTES_PATH.strip("/"):
        return None
    try:
        size = int(response_size)
    except ValueError:
        return None
    return size if size >= 0 else None


def _raw_response(headers: list[tuple[str, str]], content: bytes = b"") -> bytes:
    header_lines = "".join(f"{name}: {value}\r\n" for name, value in headers)
    return f"HTTP/1.1 {OK} OK\r\n{header_lines}\r\n".encode() + content


def _write_sync_too_large_size_hint(
    handler: BaseHTTPRequestHandler,
    path: str,
) -> bool:
    if path != TOO_LARGE_SIZE_HINT_PATH:
        return False

    handler.send_response(OK)
    handler.send_header("content-type", "application/octet-stream")
    handler.send_header("content-length", str(DEFAULT_MAX_RESPONSE_BODY_SIZE + 1))
    handler.send_header("connection", "close")
    handler.end_headers()
    return True


def _write_sync_slow_body(handler: BaseHTTPRequestHandler, path: str) -> bool:
    if path != SLOW_BODY_PATH:
        return False

    handler.send_response(OK)
    handler.send_header("content-type", "application/octet-stream")
    handler.send_header("content-length", "1")
    handler.send_header("connection", "close")
    handler.end_headers()
    handler.wfile.flush()
    time.sleep(BODY_RESPONSE_DELAY)
    with suppress(OSError):
        handler.wfile.write(b"x")
    return True


def _write_sync_incomplete_chunked_body(
    handler: BaseHTTPRequestHandler,
    path: str,
) -> bool:
    if path != INCOMPLETE_CHUNKED_BODY_PATH:
        return False

    handler.close_connection = True
    handler.send_response(OK)
    handler.send_header("content-type", "application/octet-stream")
    handler.send_header("transfer-encoding", "chunked")
    handler.send_header("connection", "close")
    handler.end_headers()
    with suppress(OSError):
        handler.wfile.write(b"1\r\nx\r\n")
        handler.wfile.flush()
    time.sleep(BODY_RESPONSE_DELAY)
    return True


def _write_sync_delayed_eof_unknown_size_bytes(
    handler: BaseHTTPRequestHandler,
    path: str,
) -> bool:
    response_size = _delayed_eof_unknown_size_bytes_response_size(path)
    if response_size is None:
        return False

    handler.close_connection = True
    handler.send_response(OK)
    handler.send_header("content-type", "application/octet-stream")
    handler.send_header("connection", "close")
    handler.end_headers()
    with suppress(OSError):
        handler.wfile.write(b"x" * response_size)
        handler.wfile.flush()
    # Without content-length the body remains incomplete until EOF; delaying
    # close keeps concurrent buffered-body budget tests deterministic.
    time.sleep(BODY_RESPONSE_DELAY)
    return True
