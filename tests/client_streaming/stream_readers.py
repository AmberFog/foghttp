__all__ = (
    "append_stream_items",
    "append_sync_stream_items",
    "collect_stream_chunks",
    "collect_sync_stream_chunks",
    "extend_stream_bytes",
    "fail_on_stream_items",
    "fail_on_sync_stream_items",
    "next_stream_chunk",
    "next_sync_stream_chunk",
    "wait_for_pending_chunk_task",
    "wait_for_pending_sync_chunk_future",
)

import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import Future
import time
from typing import TypeVar

import pytest

from .constants import PENDING_READ_START_DELAY, STREAM_READ_TIMEOUT


ItemT = TypeVar("ItemT")


async def next_stream_chunk(byte_stream: AsyncIterator[bytes]) -> bytes | None:
    return await asyncio.wait_for(anext(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def collect_stream_chunks(byte_stream: AsyncIterator[bytes]) -> list[bytes]:
    return await asyncio.wait_for(_collect_stream_chunks(byte_stream), timeout=STREAM_READ_TIMEOUT)


async def extend_stream_bytes(byte_stream: AsyncIterator[bytes], body: bytearray) -> None:
    async for chunk in byte_stream:
        body.extend(chunk)


async def append_stream_items(item_stream: AsyncIterator[ItemT], target: list[ItemT]) -> None:
    async for item in item_stream:
        target.append(item)  # noqa: PERF401 - preserve partial items before stream errors.


async def fail_on_stream_items(item_stream: AsyncIterator[ItemT], message: str) -> None:
    async for item in item_stream:
        pytest.fail(message.format(item=item))


async def wait_for_pending_chunk_task(task: asyncio.Task[bytes]) -> None:
    await asyncio.sleep(0)
    if task.done():
        task.result()
        pytest.fail("stream chunk task completed before close could cancel it")


def next_sync_stream_chunk(byte_stream: Iterator[bytes]) -> bytes | None:
    return next(byte_stream, None)


def collect_sync_stream_chunks(byte_stream: Iterator[bytes]) -> list[bytes]:
    return list(byte_stream)


def append_sync_stream_items(item_stream: Iterator[ItemT], target: list[ItemT]) -> None:
    for item in item_stream:
        target.append(item)  # noqa: PERF402 - preserve partial items before stream errors.


def fail_on_sync_stream_items(item_stream: Iterator[ItemT], message: str) -> None:
    for item in item_stream:
        pytest.fail(message.format(item=item))


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
