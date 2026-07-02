import asyncio
from contextlib import suppress
from dataclasses import dataclass
import threading
from typing import TYPE_CHECKING

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .._request_body import RequestBody
from ..messages import SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED
from .feeders import (
    close_async_source,
    close_sync_source,
    feed_async_upload_body,
    feed_sync_upload_body,
)
from .models import AsyncUploadBody, SyncUploadBody
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
        self._threads: list[threading.Thread] = []
        self._replayable = replayable

    def start(self) -> None:
        raw_body = self.raw_body
        if raw_body is None:
            return
        source = self._fresh_source()
        if is_async_stream(source):
            close_sync_source(source)
            raise TypeError(SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
        thread = threading.Thread(
            target=feed_sync_upload_body,
            args=(raw_body, source),
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

    def close(self) -> None:
        if self.raw_body is not None:
            self.raw_body.close()
        if not self._threads:
            if not self._replayable:
                close_sync_source(self._source)
            return
        current_thread = threading.current_thread()
        for thread in self._threads:
            if current_thread is not thread:
                thread.join(UPLOAD_FEEDER_JOIN_TIMEOUT)

    def _fresh_source(self) -> object:
        if self._replayable:
            return _call_body_factory(self._source)
        return self._source


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
        self._owned_sources: list[object] = []
        self._replayable = replayable

    def start(self) -> None:
        raw_body = self.raw_body
        if raw_body is None:
            return
        source = self._fresh_source()
        future = asyncio.run_coroutine_threadsafe(
            feed_async_upload_body(raw_body, source, self._ready),
            self._loop,
        )
        self._futures.append(future)

    async def aclose(self) -> None:
        if not self._futures:
            if self.raw_body is not None:
                self.raw_body.close()
            if not self._replayable:
                await close_async_source(self._source)
            return
        for pending_future in self._futures:
            if not pending_future.done():
                pending_future.cancel()
        await self._drain_futures()
        await self._close_owned_sources()
        if self.raw_body is not None:
            self.raw_body.close()

    def _fresh_source(self) -> object:
        if self._replayable:
            source = _call_body_factory(self._source)
            self._owned_sources.append(source)
            return source
        return self._source

    async def _close_owned_sources(self) -> None:
        close_tasks = [_close_owned_source(source) for source in self._owned_sources]
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
        self._loop.call_soon_threadsafe(self._ready.set)


def prepare_sync_upload_body(body: RequestBody) -> SyncUploadBody:
    if body.stream is None:
        return _BufferedUploadBody(body.content)
    if is_async_stream(body.stream):
        raise TypeError(SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
    return _SyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
    )


def prepare_async_upload_body(body: RequestBody) -> AsyncUploadBody:
    if body.stream is None:
        return _BufferedUploadBody(body.content)
    return _AsyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
    )


def _call_body_factory(source: object) -> object:
    return source()  # type: ignore[operator]


async def _close_owned_source(source: object) -> None:
    if is_async_stream(source):
        await close_async_source(source)
        return
    close_sync_source(source)
