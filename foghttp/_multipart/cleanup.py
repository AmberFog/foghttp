import asyncio
from collections.abc import Callable
from concurrent.futures import Future as ConcurrentFuture
import sys
import threading
from typing import TypeVar

from .._upload_body import cleanup as upload_cleanup
from .._upload_body.cleanup_callbacks import close_async_source_from_sync, close_sync_source
from ..errors import LifecycleError
from .models import MultipartFile


_MULTIPART_CLOSED = "multipart upload is closed"
_IteratorResult = TypeVar("_IteratorResult")


class MultipartFileCleanup:
    def __init__(
        self,
        file: MultipartFile,
        *,
        source_cleanup: upload_cleanup.UploadSourceCleanup | None = None,
        iterator_only: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._closing = False
        self._iterator: upload_cleanup.UploadSourceCleanup | None = None
        self._source = source_cleanup
        if self._source is None and file.close_source and not iterator_only:
            self._source = upload_cleanup.UploadSourceCleanup(file.content)

    def create_iterator(self, factory: Callable[[], _IteratorResult], source: object) -> _IteratorResult:
        with self._lock:
            if self._closing:
                raise LifecycleError(_MULTIPART_CLOSED)
        if self._source is None:
            reservation = upload_cleanup.reserve_cleanup(1)
            try:
                iterator = factory()
            except BaseException:
                reservation.release()
                raise
            if iterator is source:
                reservation.release()
                return iterator
            self._bind(upload_cleanup.UploadSourceCleanup(iterator, reservation=reservation))
        else:
            iterator = self._source.create_iterator(factory)
            if iterator is not source:
                self._bind(self._source.iteration.track(iterator))
        return iterator

    def close(self, *, preserve_error: bool = False) -> None:
        active_error = sys.exception() if preserve_error else None
        completion = self.start_sync_cleanup()
        if completion is None:
            return
        try:
            completion.result(timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT)
        except TimeoutError:
            return
        except BaseException:
            if active_error is None:
                raise

    async def aclose(self, *, preserve_error: bool = False) -> None:
        active_error = sys.exception() if preserve_error else None
        owner = self.start_part(on_loop=True, prefer_async=True)
        if owner is None:
            return
        task = owner.waiters.future()
        try:
            done = await asyncio.wait((task,), timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT)
            if task in done[0]:
                task.result()
        except BaseException:
            if active_error is None:
                raise

    def start_sync_cleanup(self) -> ConcurrentFuture[None] | None:
        owner = self.start_part(on_loop=False, prefer_async=False)
        return None if owner is None else owner.completion

    def start_part(self, *, on_loop: bool, prefer_async: bool) -> upload_cleanup.UploadSourceCleanup | None:
        with self._lock:
            self._closing = True
            owner = self._source or self._iterator
            predecessor = None if self._source is None else self._iterator
        if owner is None:
            return None
        if on_loop:
            accepted = owner.start_async_cleanup(after=predecessor) is not None
        else:
            close_source = close_async_source_from_sync if prefer_async else close_sync_source
            accepted = owner.start_sync_cleanup(after=predecessor, close_source=close_source) is not None
        return owner if accepted else None

    def _bind(self, cleanup: upload_cleanup.UploadSourceCleanup) -> None:
        with self._lock:
            self._iterator = cleanup
            closing = self._closing
        if closing:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                cleanup.start_sync_cleanup()
            else:
                cleanup.start_async_cleanup()
