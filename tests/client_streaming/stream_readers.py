__all__ = (
    "collect_stream_chunks",
    "collect_sync_stream_chunks",
    "next_stream_chunk",
    "next_sync_stream_chunk",
    "wait_for_pending_chunk_task",
    "wait_for_pending_sync_chunk_future",
)

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import Future
import time

import pytest

from .constants import PENDING_READ_START_DELAY, STREAM_READ_TIMEOUT


async def next_stream_chunk(byte_stream: AsyncIterator[bytes]) -> bytes | None:
    return await asyncio.wait_for(anext(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def collect_stream_chunks(byte_stream: AsyncIterator[bytes]) -> list[bytes]:
    return await asyncio.wait_for(_collect_stream_chunks(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def wait_for_pending_chunk_task(task: asyncio.Task[bytes]) -> None:
    await asyncio.sleep(0)
    if task.done():
        task.result()
        pytest.fail("stream chunk task completed before close could cancel it")


def next_sync_stream_chunk(byte_stream: Iterator[bytes]) -> bytes | None:
    return next(byte_stream, None)


def collect_sync_stream_chunks(byte_stream: Iterator[bytes]) -> list[bytes]:
    return list(byte_stream)


def wait_for_pending_sync_chunk_future(future: Future[bytes | None]) -> None:
    deadline = time.monotonic() + STREAM_READ_TIMEOUT
    while time.monotonic() < deadline:
        if future.done():
            future.result()
            pytest.fail("stream chunk future completed before close could abort it")
        if future.running():
            time.sleep(PENDING_READ_START_DELAY)
            if future.done():
                future.result()
                pytest.fail("stream chunk future completed before close could abort it")
            return
        time.sleep(PENDING_READ_START_DELAY)

    pytest.fail("stream chunk future did not start before close could abort it")


async def _collect_stream_chunks(byte_stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in byte_stream]
