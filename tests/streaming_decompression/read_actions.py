__all__ = (
    "collect_async_into",
    "collect_sync_into",
    "read_after_signal",
    "read_async_prefix",
    "read_async_until_transport_eof",
    "read_sync_prefix",
    "read_sync_until_transport_eof",
)

import asyncio
from collections.abc import AsyncIterator, Iterator

import foghttp


def collect_sync_into(iterator: Iterator[bytes], delivered: bytearray) -> None:
    for chunk in iterator:
        delivered.extend(chunk)


async def collect_async_into(iterator: AsyncIterator[bytes], delivered: bytearray) -> None:
    async for chunk in iterator:
        delivered.extend(chunk)


async def read_after_signal(iterator: AsyncIterator[bytes], started: asyncio.Event) -> bytes:
    started.set()
    return await anext(iterator)


def read_sync_prefix(iterator: Iterator[bytes], size: int) -> bytes:
    delivered = bytearray()
    while len(delivered) < size:
        delivered.extend(next(iterator))
    return bytes(delivered)


async def read_async_prefix(iterator: AsyncIterator[bytes], size: int) -> bytes:
    delivered = bytearray()
    while len(delivered) < size:
        delivered.extend(await anext(iterator))
    return bytes(delivered)


def read_sync_until_transport_eof(client: foghttp.Client, iterator: Iterator[bytes]) -> bytes:
    delivered = bytearray()
    for chunk in iterator:
        delivered.extend(chunk)
        if client.stats().response_body_reuse_eligible == 1:
            return bytes(delivered)
    msg = "decoded stream exhausted before observing clean transport with delivery pending"
    raise AssertionError(msg)


async def read_async_until_transport_eof(client: foghttp.AsyncClient, iterator: AsyncIterator[bytes]) -> bytes:
    delivered = bytearray()
    async for chunk in iterator:
        delivered.extend(chunk)
        if client.stats().response_body_reuse_eligible == 1:
            return bytes(delivered)
    msg = "decoded stream exhausted before observing clean transport with delivery pending"
    raise AssertionError(msg)
