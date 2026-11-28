__all__ = ("CloseStream", "close_async_iterator", "close_iterator", "closing_stream")

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Protocol, runtime_checkable


class CloseStream(Protocol):
    def __call__(self, *, suppress_telemetry_errors: bool) -> None: ...


@contextmanager
def closing_stream(close: CloseStream | None) -> Iterator[None]:
    has_primary_error = False
    try:
        yield
    except GeneratorExit:
        raise
    except BaseException:
        has_primary_error = True
        raise
    finally:
        if close is not None:
            close(suppress_telemetry_errors=has_primary_error)


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
