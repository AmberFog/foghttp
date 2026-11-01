from collections.abc import AsyncIterator, Iterator
import threading

from .constants import CALLBACK_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


class SyncCloseIterator(SyncCloseGate, Iterator[bytes]):
    def __next__(self) -> bytes:
        raise StopIteration


class AsyncCloseIterator(AsyncCloseGate, AsyncIterator[bytes]):
    async def __anext__(self) -> bytes:
        raise StopAsyncIteration


class FailingIteratorSource:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.iteration_calls = 0
        self.close_calls = 0

    def __iter__(self) -> Iterator[bytes]:
        self.iteration_calls += 1
        raise self.error

    def close(self) -> None:
        self.close_calls += 1


class SyncIteratorFactory:
    def __init__(self) -> None:
        self.iterator = SyncCloseIterator()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.close_calls = 0

    def __iter__(self) -> SyncCloseIterator:
        self.entered.set()
        if not self.release.wait(CALLBACK_WATCHDOG):
            message = "iterator factory watchdog expired"
            raise RuntimeError(message)
        return self.iterator

    def close(self) -> None:
        self.close_calls += 1


class AsyncIteratorFactory:
    def __init__(self) -> None:
        self.iterator = AsyncCloseIterator()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.close_calls = 0

    def __aiter__(self) -> AsyncCloseIterator:
        self.entered.set()
        if not self.release.wait(CALLBACK_WATCHDOG):
            message = "async iterator factory watchdog expired"
            raise RuntimeError(message)
        return self.iterator

    def close(self) -> None:
        self.close_calls += 1
