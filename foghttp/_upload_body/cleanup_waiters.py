from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING
from weakref import WeakSet


if TYPE_CHECKING:
    from concurrent.futures import Future

from .thread_bridge import consume_future_exception


class CleanupWaiters:
    """Weak loop-local waiters for one process-owned cleanup completion."""

    def __init__(self, completion: Future[None]) -> None:
        self._completion = completion
        self._current: asyncio.Future[None] | None = None
        self._waiters: WeakSet[asyncio.Future[None]] = WeakSet()
        self._lock = threading.Lock()
        completion.add_done_callback(self.notify)

    def future(self) -> asyncio.Future[None]:
        loop = asyncio.get_running_loop()
        future = self._current
        if future is not None and not future.cancelled() and future.get_loop() is loop:
            return future
        future = loop.create_future()
        self._current = future
        with self._lock:
            self._waiters.add(future)
        future.add_done_callback(consume_future_exception)
        if self._completion.done():
            _settle_future(future, self._completion)
        return future

    def notify(self, completion: Future[None]) -> None:
        with self._lock:
            futures = tuple(self._waiters)
        for future in futures:
            if not future.done() and not future.get_loop().is_closed():
                _notify_future(future, completion)


def _notify_future(future: asyncio.Future[None], completion: Future[None]) -> None:
    try:
        future.get_loop().call_soon_threadsafe(_settle_future, future, completion)
    except RuntimeError:
        return


def _settle_future(future: asyncio.Future[None], completion: Future[None]) -> None:
    if future.done():
        return
    error = consume_future_exception(completion)
    if error is None:
        future.set_result(None)
    else:
        future.set_exception(error)
