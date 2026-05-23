__all__ = ("collect_stream_chunks", "next_stream_chunk", "wait_for_pending_chunk_task")

import asyncio
from collections.abc import AsyncIterator

import pytest

from .constants import STREAM_READ_TIMEOUT


async def next_stream_chunk(byte_stream: AsyncIterator[bytes]) -> bytes | None:
    return await asyncio.wait_for(anext(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def collect_stream_chunks(byte_stream: AsyncIterator[bytes]) -> list[bytes]:
    return await asyncio.wait_for(_collect_stream_chunks(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def wait_for_pending_chunk_task(task: asyncio.Task[bytes]) -> None:
    await asyncio.sleep(0)
    if task.done():
        task.result()
        pytest.fail("stream chunk task completed before close could cancel it")


async def _collect_stream_chunks(byte_stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in byte_stream]
