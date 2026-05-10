__all__ = ("benchmark_server",)

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from bench.constants import MAX_SPLIT_ONCE
from bench.scenarios import BYTES_64K, HTTP_REASONS, SMALL_JSON


MIN_REDIRECT_PATH_PARTS = 2


@asynccontextmanager
async def benchmark_server() -> Any:
    server = await asyncio.start_server(handle_connection, "127.0.0.1", 0)
    sockets = server.sockets or []
    if not sockets:
        msg = "benchmark server did not bind a socket"
        raise RuntimeError(msg)
    host, port = sockets[0].getsockname()[:2]
    async with server:
        yield f"http://{host}:{port}"


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    keep_alive = True
    try:
        while keep_alive:
            try:
                header_block = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                break

            first_line, headers = parse_request_headers(header_block)
            if not first_line:
                break

            try:
                method, path, _version = first_line.split(" ", MAX_SPLIT_ONCE + 1)
            except ValueError:
                break

            content_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(content_length) if content_length else b""
            keep_alive = headers.get("connection", "").lower() != "close"

            delay_ms = delay_from_path(path)
            if delay_ms is not None:
                await asyncio.sleep(delay_ms / 1000)

            status_code, response_body, content_type, extra_headers = build_response(path, body)
            await write_response(
                writer,
                method=method,
                status_code=status_code,
                body=response_body,
                content_type=content_type,
                keep_alive=keep_alive,
                extra_headers=extra_headers,
            )
    finally:
        writer.close()
        await writer.wait_closed()


def parse_request_headers(header_block: bytes) -> tuple[str, dict[str, str]]:
    lines = header_block.decode("latin1").split("\r\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return lines[0], headers


def build_response(path: str, body: bytes) -> tuple[int, bytes, bytes, dict[str, str]]:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    redirect = redirect_response(request_path)
    if redirect is not None:
        return redirect
    if request_path == "/json-small":
        return 200, SMALL_JSON, b"application/json", {}
    if request_path == "/bytes-64k":
        return 200, BYTES_64K, b"application/octet-stream", {}
    if request_path == "/echo":
        return 200, body, b"application/octet-stream", {}
    if request_path.startswith("/delay/"):
        return (
            200,
            SMALL_JSON,
            b"application/json",
            {"x-benchmark-delay-ms": request_path.rsplit("/", MAX_SPLIT_ONCE)[1]},
        )
    return 404, b"not found", b"text/plain", {}


def delay_from_path(path: str) -> int | None:
    request_path = path.split("?", MAX_SPLIT_ONCE)[0]
    if not request_path.startswith("/delay/"):
        return None
    return int(request_path.rsplit("/", MAX_SPLIT_ONCE)[1])


def redirect_response(path: str) -> tuple[int, bytes, bytes, dict[str, str]] | None:
    parts = path.strip("/").split("/")
    if len(parts) < MIN_REDIRECT_PATH_PARTS or parts[0] != "redirect":
        return None

    status_code = int(parts[1])
    target = "/" + "/".join(parts[MIN_REDIRECT_PATH_PARTS:]) if len(parts) > MIN_REDIRECT_PATH_PARTS else "/json-small"
    return status_code, b"", b"text/plain", {"location": target}


async def write_response(
    writer: asyncio.StreamWriter,
    *,
    method: str,
    status_code: int,
    body: bytes,
    content_type: bytes,
    keep_alive: bool,
    extra_headers: dict[str, str],
) -> None:
    response_body = b"" if method == "HEAD" else body
    reason = HTTP_REASONS.get(status_code, "OK")
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        f"content-length: {len(body)}",
        f"content-type: {content_type.decode()}",
        f"connection: {'keep-alive' if keep_alive else 'close'}",
    ]
    headers.extend(f"{name}: {value}" for name, value in extra_headers.items())
    writer.write("\r\n".join(headers).encode() + b"\r\n\r\n" + response_body)
    await writer.drain()
