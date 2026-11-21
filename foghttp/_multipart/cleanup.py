import asyncio
from collections.abc import Callable
from concurrent.futures import Future as ConcurrentFuture
import sys
import threading
from typing import TypeVar

from .._upload_body import cleanup as upload_cleanup
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
        task = self.start_async_cleanup()
        if task is None:
            return
        try:
            done = await asyncio.wait((task,), timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT)
            if task in done[0]:
                task.result()
        except BaseException:
            if active_error is None:
                raise

    def start_sync_cleanup(self) -> ConcurrentFuture[None] | None:
        with self._lock:
            self._closing = True
        if self._source is not None:
            return self._source.start_sync_cleanup(after=self._iterator)
        if self._iterator is not None:
            return self._iterator.start_sync_cleanup()
        return None

    def start_async_cleanup(self) -> asyncio.Future[None] | None:
        with self._lock:
            self._closing = True
        if self._source is not None:
            return self._source.start_async_cleanup(after=self._iterator)
        if self._iterator is not None:
            return self._iterator.start_async_cleanup()
        return None

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
