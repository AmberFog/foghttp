import asyncio
from contextlib import suppress
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .._request_body import RequestBody
from ..messages import SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED
from . import (
    cleanup as upload_cleanup,
    models as upload_models,
)
from .feeders import feed_async_upload_body, feed_sync_upload_body
from .predicates import is_async_stream


if TYPE_CHECKING:
    from concurrent.futures import Future


UPLOAD_FEEDER_JOIN_TIMEOUT = 0.1
ASYNC_UPLOAD_FEEDER_JOIN_TIMEOUT = 1.0


@dataclass(slots=True)
class _BufferedUploadBody:
    buffered_body: bytes | None
    raw_body: "_foghttp.RawUploadBody | None" = None

    def close(self) -> None: ...

    async def aclose(self) -> None: ...


class _SyncStreamingUploadBody:
    def __init__(
        self,
        source: object,
        content_length: int | None,
        *,
        replayable: bool,
    ) -> None:
        self.buffered_body: bytes | None = None
        self.raw_body: _foghttp.RawUploadBody | None = _foghttp.RawUploadBody(
            content_length,
            self.start,
            replayable,
            None,
        )
        self._source = source
        self._source_cleanups = [] if replayable else [upload_cleanup.UploadSourceCleanup(source)]
        self._threads: list[threading.Thread] = []
        self._replayable = replayable

    def start(self, raw_body: _foghttp.RawUploadBody) -> None:
        source, source_cleanup = self._fresh_source()
        if is_async_stream(source):
            source_cleanup.aclose_from_sync()
            raise TypeError(SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
        thread = threading.Thread(
            target=feed_sync_upload_body,
            args=(raw_body, source, source_cleanup),
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def close(self) -> None:
        if self.raw_body is not None:
            self.raw_body.close()
        for source_cleanup in self._source_cleanups:
            source_cleanup.close()
        current_thread = threading.current_thread()
        for thread in self._threads:
            if current_thread is not thread:
                thread.join(UPLOAD_FEEDER_JOIN_TIMEOUT)

    def _fresh_source(self) -> tuple[object, upload_cleanup.UploadSourceCleanup]:
        if self._replayable:
            source, source_cleanup, source_error = _prepare_factory_source(self._source)
            self._source_cleanups.append(source_cleanup)
            if source_error is not None:
                if is_async_stream(source):
                    source_cleanup.aclose_from_sync()
                else:
                    source_cleanup.close()
                raise source_error
            return source, source_cleanup
        return self._source, self._source_cleanups[0]


class _AsyncStreamingUploadBody:
    def __init__(
        self,
        source: object,
        content_length: int | None,
        *,
        replayable: bool,
    ) -> None:
        self.buffered_body: bytes | None = None
        self.raw_body: _foghttp.RawUploadBody | None = _foghttp.RawUploadBody(
            content_length,
            self.start,
            replayable,
            self._notify_ready,
        )
        self._source = source
        self._loop = asyncio.get_running_loop()
        self._ready = asyncio.Event()
        self._futures: list[Future[None]] = []
        self._source_cleanups = [] if replayable else [upload_cleanup.UploadSourceCleanup(source)]
        self._replayable = replayable

    def start(self, raw_body: _foghttp.RawUploadBody) -> None:
        source, source_cleanup = self._fresh_source()
        future = asyncio.run_coroutine_threadsafe(
            feed_async_upload_body(raw_body, source, source_cleanup, self._ready),
            self._loop,
        )
        self._futures.append(future)

    async def aclose(self) -> None:
        if self.raw_body is not None:
            self.raw_body.close()
        for pending_future in self._futures:
            if not pending_future.done():
                pending_future.cancel()
        try:
            await self._drain_futures()
        except BaseException:
            for source_cleanup in self._source_cleanups:
                source_cleanup.start_async_cleanup()
            raise
        for source_cleanup in self._source_cleanups:
            source_cleanup.start_async_cleanup()
        await self._close_sources()

    def _fresh_source(self) -> tuple[object, upload_cleanup.UploadSourceCleanup]:
        if self._replayable:
            source, source_cleanup, source_error = _prepare_factory_source(self._source)
            self._source_cleanups.append(source_cleanup)
            if source_error is not None:
                raise source_error
            return source, source_cleanup
        return self._source, self._source_cleanups[0]

    async def _close_sources(self) -> None:
        close_tasks = [source_cleanup.aclose() for source_cleanup in self._source_cleanups]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

    async def _drain_futures(self) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(
                    *(asyncio.wrap_future(stored_future) for stored_future in self._futures),
                    return_exceptions=True,
                ),
                timeout=ASYNC_UPLOAD_FEEDER_JOIN_TIMEOUT,
            )

    def _notify_ready(self) -> None:
        if self._loop.is_closed():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            self._ready.set()
            return
        try:
            self._loop.call_soon_threadsafe(self._ready.set)
        except RuntimeError:
            return


def prepare_sync_upload_body(body: RequestBody) -> upload_models.SyncUploadBody:
    if body.stream is None:
        return _BufferedUploadBody(body.content)
    if is_async_stream(body.stream):
        raise TypeError(SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
    return _SyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
    )


def prepare_async_upload_body(body: RequestBody) -> upload_models.AsyncUploadBody:
    if body.stream is None:
        return _BufferedUploadBody(body.content)
    return _AsyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
    )


def _prepare_factory_source(
    source_factory: object,
) -> tuple[object, upload_cleanup.UploadSourceCleanup, BaseException | None]:
    source = source_factory()  # type: ignore[operator]
    if isinstance(source, upload_cleanup.UploadSourceFactoryFailure):
        return source.source, upload_cleanup.UploadSourceCleanup(source.source), source.error
    return source, upload_cleanup.UploadSourceCleanup(source), None
