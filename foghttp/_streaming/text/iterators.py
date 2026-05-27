__all__ = ("close_async_iterator", "close_iterator")

from collections.abc import AsyncIterator, Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class _ClosableIterator(Protocol):
    def close(self) -> None: ...


@runtime_checkable
class _AsyncClosableIterator(Protocol):
    async def aclose(self) -> None: ...


def close_iterator(iterator: Iterator[object]) -> None:
    if isinstance(iterator, _ClosableIterator):
        iterator.close()


async def close_async_iterator(iterator: AsyncIterator[object]) -> None:
    if isinstance(iterator, _AsyncClosableIterator):
        await iterator.aclose()
