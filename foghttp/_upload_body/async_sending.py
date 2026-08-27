import asyncio
from typing import TYPE_CHECKING, Protocol


if TYPE_CHECKING:
    from collections.abc import Awaitable


class AsyncUploadSender(Protocol):
    def send_nowait(self, chunk: bytes) -> bool: ...

    def send_final_nowait(self, chunk: bytes) -> bool: ...

    def fail_nowait(self, message: str) -> bool: ...

    def is_closed(self) -> bool: ...

    def close(self) -> None: ...


async def send_async_upload_chunk(
    raw_body: AsyncUploadSender,
    ready: asyncio.Event,
    chunk: bytes,
    *,
    final: bool = False,
) -> bool:
    while True:
        ready.clear()
        send = raw_body.send_final_nowait if final else raw_body.send_nowait
        if send(chunk):
            if not chunk and not final:
                await asyncio.sleep(0)
                return not raw_body.is_closed()
            return True
        if raw_body.is_closed():
            return False
        await ready.wait()


async def fail_async_upload_body(
    raw_body: AsyncUploadSender,
    ready: asyncio.Event,
    message: str,
) -> None:
    while True:
        ready.clear()
        if raw_body.fail_nowait(message):
            return
        if raw_body.is_closed():
            return
        await ready.wait()


async def handle_async_upload_error(
    raw_body: AsyncUploadSender,
    ready: asyncio.Event,
    error: BaseException,
    *,
    task_is_cancelling: bool,
) -> BaseException | None:
    if isinstance(error, asyncio.CancelledError) and task_is_cancelling:
        return error
    if isinstance(error, (asyncio.CancelledError, Exception)):
        try:
            await fail_async_upload_body(raw_body, ready, upload_error_message(error))
        except BaseException as report_error:  # noqa: BLE001
            return report_error
        return None
    return error


def upload_error_message(error: BaseException) -> str:
    try:
        message = str(error)
    except BaseException:  # noqa: BLE001
        return error.__class__.__name__
    return message or error.__class__.__name__


async def suppress_async_cleanup_error(cleanup: "Awaitable[None]") -> None:
    try:
        await cleanup
    except BaseException as cleanup_error:
        if isinstance(cleanup_error, asyncio.CancelledError):
            raise
