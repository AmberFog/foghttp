__all__ = (
    "ForkResult",
    "open_async_stream_response",
    "read_async_stream_body",
    "read_next_async_stream_chunk",
    "request_with_async_client",
    "request_with_new_async_client",
    "request_with_new_sync_client",
    "request_with_sync_client",
    "run_in_fork",
    "stream_with_async_client",
    "stream_with_sync_client",
)

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
import json
import os
import select
import signal
import warnings

import foghttp
from foghttp.methods import GET
from foghttp.status_codes.success import OK


CHILD_RESULT_BYTES = 65_536
FORK_CHILD_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class ForkResult:
    ok: bool
    error_type: str
    message: str
    exit_status: int


def run_in_fork(action: Callable[[], object]) -> ForkResult:
    read_fd, write_fd = os.pipe()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"This process .* is multi-threaded, use of fork\(\) may lead to deadlocks in the child.",
            category=DeprecationWarning,
        )
        pid = os.fork()
    if pid == 0:
        _run_child_action(read_fd, write_fd, action)

    os.close(write_fd)
    try:
        payload = _read_child_result(read_fd)
    except BaseException:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        raise
    finally:
        os.close(read_fd)
        _pid, exit_status = os.waitpid(pid, 0)
    result = json.loads(payload.decode())
    return ForkResult(
        ok=result["ok"],
        error_type=result["error_type"],
        message=result["message"],
        exit_status=exit_status,
    )


def request_with_sync_client(client: foghttp.Client, url: str) -> None:
    response = client.get(url)
    _ensure_ok_response(response.status_code)


def request_with_new_sync_client(url: str) -> None:
    with foghttp.Client() as client:
        request_with_sync_client(client, url)


def request_with_async_client(client: foghttp.AsyncClient, url: str) -> None:
    asyncio.run(_request_with_async_client(client, url))


def stream_with_sync_client(client: foghttp.Client, url: str) -> None:
    with client.stream(GET, url) as response:
        _ensure_ok_response(response.status_code)


def stream_with_async_client(client: foghttp.AsyncClient, url: str) -> None:
    asyncio.run(_stream_with_async_client(client, url))


def request_with_new_async_client(url: str) -> None:
    asyncio.run(_request_with_new_async_client(url))


def open_async_stream_response(
    client: foghttp.AsyncClient,
    url: str,
) -> foghttp.AsyncStreamResponse:
    return asyncio.run(_open_async_stream_response(client, url))


def read_next_async_stream_chunk(response: foghttp.AsyncStreamResponse) -> bytes:
    return asyncio.run(anext(response.aiter_bytes()))


def read_async_stream_body(response: foghttp.AsyncStreamResponse) -> bytes:
    return asyncio.run(_read_async_stream_body(response))


def _run_child_action(read_fd: int, write_fd: int, action: Callable[[], object]) -> None:
    os.close(read_fd)
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - fork child must report arbitrary test failures.
        _write_child_result(
            write_fd,
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "message": str(exc),
            },
        )
    else:
        _write_child_result(
            write_fd,
            {
                "ok": True,
                "error_type": "",
                "message": "",
            },
        )
    finally:
        os.close(write_fd)
        os._exit(0)


def _read_child_result(read_fd: int) -> bytes:
    readable, _writable, _errors = select.select([read_fd], [], [], FORK_CHILD_TIMEOUT)
    if not readable:
        msg = "forked child did not finish before timeout"
        raise AssertionError(msg)

    payload = os.read(read_fd, CHILD_RESULT_BYTES)
    if not payload:
        msg = "forked child exited without reporting a result"
        raise AssertionError(msg)
    return payload


def _write_child_result(write_fd: int, result: dict[str, object]) -> None:
    os.write(write_fd, json.dumps(result).encode())


async def _request_with_async_client(client: foghttp.AsyncClient, url: str) -> None:
    response = await client.get(url)
    _ensure_ok_response(response.status_code)


async def _stream_with_async_client(client: foghttp.AsyncClient, url: str) -> None:
    async with client.stream(GET, url) as response:
        _ensure_ok_response(response.status_code)


async def _request_with_new_async_client(url: str) -> None:
    async with foghttp.AsyncClient() as client:
        await _request_with_async_client(client, url)


async def _open_async_stream_response(
    client: foghttp.AsyncClient,
    url: str,
) -> foghttp.AsyncStreamResponse:
    return await client.stream(GET, url).__aenter__()


async def _read_async_stream_body(response: foghttp.AsyncStreamResponse) -> bytes:
    return b"".join([chunk async for chunk in response.aiter_bytes()])


def _ensure_ok_response(status_code: int) -> None:
    if status_code != OK:
        msg = f"expected child request to return {OK}, got {status_code}"
        raise AssertionError(msg)
