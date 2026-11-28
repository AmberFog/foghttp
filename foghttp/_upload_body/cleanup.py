__all__ = ("current_task_is_cancelling", "reserve_cleanup")

import asyncio
from concurrent.futures import Future
from contextvars import Context, copy_context
from functools import partial, partialmethod
import os
from typing import TYPE_CHECKING, TypeVar


if TYPE_CHECKING:
    from collections.abc import Callable

from . import cleanup_group, cleanup_start, thread_bridge
from .cleanup_callbacks import (
    CloseSource,
    close_async_source_from_sync,
    close_sync_source,
    current_task_is_cancelling,
    source_async_close,
)
from .cleanup_iteration import CleanupIteration
from .cleanup_owner import CleanupReservation, reserve_cleanup
from .cleanup_waiters import CleanupWaiters


ASYNC_SOURCE_CLOSE_TIMEOUT = 1.0
_IteratorT = TypeVar("_IteratorT")


class UploadSourceCleanup:
    def __init__(
        self,
        source: object,
        *,
        context: Context | None = None,
        reservation: CleanupReservation | None = None,
    ) -> None:
        self._source = source
        self.context = copy_context() if context is None else context.copy()
        self._reservation = reserve_cleanup() if reservation is None else reservation
        self.completion = self._reservation.completion
        self.iteration = CleanupIteration(self, self._reservation)
        self.waiters = CleanupWaiters(self.completion)
        self._sync_error_reported = False

    def create_iterator(self, factory: "Callable[[], _IteratorT]") -> _IteratorT:
        self.iteration.reserve(creating=True)
        try:
            iterator = factory()
        except BaseException:
            self.iteration.release()
            raise
        if iterator is self._source:
            self.iteration.release()
        else:
            self.iteration.track(iterator)
        return iterator

    @cleanup_start.defer_worker_interrupts()
    def start_sync_cleanup(
        self,
        *,
        after: "UploadSourceCleanup | None" = None,
        close_source: CloseSource = close_sync_source,
        group_loop: asyncio.AbstractEventLoop | None = None,
    ) -> Future[None] | None:
        if self._reservation.pid != os.getpid():
            return None
        predecessor = None if after is None else after.start_sync_cleanup(close_source=close_source)
        dependency, submit = self.iteration.claim(predecessor)
        if not submit:
            self._reservation.owner.retry()
            return self.completion
        if (
            group_loop is not None
            and isinstance(self._source, cleanup_group.GroupedUploadSource)
            and self._source.needs_request_loop
        ):
            return self._reservation.submit_async(
                self._source.start_async_parts,
                loop=group_loop,
                context=self.context,
                after=dependency,
            )
        return self._reservation.submit_sync(
            partial(close_source, self._source),
            context=self.context,
            after=dependency,
        )

    def close(self, *, close_source: CloseSource = close_sync_source) -> None:
        completion = self.start_sync_cleanup(close_source=close_source)
        if completion is None:
            return
        try:
            if completion.exception(timeout=ASYNC_SOURCE_CLOSE_TIMEOUT) is None:
                return
        except TimeoutError:
            return
        error = self.consume_sync_error()
        if error is not None:
            raise error from None

    async def aclose(self, *, after: "UploadSourceCleanup | None" = None, bounded: bool = True) -> None:
        future = self.start_async_cleanup(after=after)
        if future is None:
            return
        timeout = ASYNC_SOURCE_CLOSE_TIMEOUT if bounded else None
        done, _pending = await asyncio.wait((future,), timeout=timeout)
        if future in done:
            future.result()

    @cleanup_start.defer_worker_interrupts()
    def start_async_cleanup(
        self,
        *,
        interrupt: bool = False,
        after: "UploadSourceCleanup | None" = None,
    ) -> asyncio.Future[None] | None:
        if self._reservation.pid != os.getpid():
            return None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return None
        predecessor = None
        if after is not None:
            after.start_async_cleanup()
            predecessor = after.completion
        dependency, submit = self.iteration.claim(predecessor)
        if submit:
            with cleanup_start.independent_worker_interrupts():
                callback = None if interrupt else self.context.copy().run(source_async_close, self._source)
            if callback is None:
                self._reservation.submit_sync(
                    partial(close_sync_source, self._source),
                    context=self.context,
                    after=dependency,
                )
            else:
                self._reservation.submit_async(callback, context=self.context, after=dependency)
        else:
            self._reservation.owner.retry()
        return self.waiters.future()

    def consume_sync_error(self) -> BaseException | None:
        if self._reservation.pid != os.getpid() or not self.completion.done():
            return None
        with self.iteration.lock:
            if self._sync_error_reported:
                return None
            self._sync_error_reported = True
        return thread_bridge.consume_future_exception(self.completion)

    interrupt = close
    aclose_from_sync = partialmethod(close, close_source=close_async_source_from_sync)


class UploadSourceFactoryFailure:
    __slots__ = ("error", "source")

    def __init__(self, source: object, error: BaseException) -> None:
        self.source = source
        self.error = error
