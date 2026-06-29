import asyncio
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from foghttp import _foghttp


async def send_async_upload_chunk(
    raw_body: "_foghttp.RawUploadBody",
    ready: asyncio.Event,
    chunk: bytes,
) -> bool:
    while True:
        ready.clear()
        if raw_body.send_nowait(chunk):
            return True
        if raw_body.is_closed():
            return False
        await ready.wait()


async def fail_async_upload_body(
    raw_body: "_foghttp.RawUploadBody",
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
