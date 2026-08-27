import asyncio

from .._upload_body import cleanup as upload_cleanup
from .._upload_body.thread_bridge import run_daemon_callbacks_bounded
from .models import MultipartFile


class MultipartFileCleanup:
    def __init__(self, file: MultipartFile) -> None:
        self._iterator: upload_cleanup.UploadSourceCleanup | None = None
        self._source = upload_cleanup.UploadSourceCleanup(file.content) if file.close_source else None

    def track_iterator(self, iterator: object, source: object) -> None:
        if iterator is not source:
            self._iterator = upload_cleanup.UploadSourceCleanup(iterator)

    def close(self) -> None:
        if self._iterator is None and self._source is None:
            return
        cleanup_error = run_daemon_callbacks_bounded(
            (self._close_sync,),
            timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
        )
        if cleanup_error is not None:
            raise cleanup_error

    def start_async_cleanup(self) -> asyncio.Task[None] | None:
        if self._source is not None:
            return self._source.start_async_cleanup(after=self._iterator)
        if self._iterator is not None:
            return self._iterator.start_async_cleanup()
        return None

    def _close_sync(self) -> None:
        cleanup_error: BaseException | None = None
        for cleanup in (self._iterator, self._source):
            if cleanup is None:
                continue
            try:
                cleanup.interrupt()
            except BaseException as error:  # noqa: BLE001
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error
