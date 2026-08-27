import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator

    from foghttp import _foghttp

from .async_sending import (
    handle_async_upload_error,
    send_async_upload_chunk,
    suppress_async_cleanup_error,
    upload_error_message,
)
from .chunks import async_body_chunks, sync_body_chunks
from .cleanup import UploadSourceCleanup, current_task_is_cancelling
from .predicates import is_async_stream
from .thread_bridge import UploadFeederState, run_sync_upload_feeder


class _SyncUploadFeeder:
    def __init__(
        self,
        raw_body: "_foghttp.RawUploadBody",
        source: object,
        source_cleanup: UploadSourceCleanup,
        feeder_state: UploadFeederState,
    ) -> None:
        self._raw_body = raw_body
        self._source = source
        self._source_cleanup = source_cleanup
        self._state = feeder_state
        self._iterator: Iterator[object] | None = None
        self._final_chunk: bytes | None = None
        self._primary_error: BaseException | None = None
        self._should_finish = False
        self._source_error_reported = False

    def run(self) -> None:
        self._feed()
        self._close_sources()
        if self._primary_error is None:
            self._complete_body()
        error = self._primary_error
        if error is not None:
            self._state.publish(error)
            raise error

    def _feed(self) -> None:
        try:
            self._iterator = iter(cast("Iterable[object]", self._source))
            self._feed_chunks()
        except (asyncio.CancelledError, Exception) as error:  # noqa: BLE001
            self._report_error(error)
        except BaseException as error:  # noqa: BLE001
            with suppress(BaseException):
                self._raw_body.close()
            self._primary_error = error
            self._state.publish(error)

    def _feed_chunks(self) -> None:
        for chunk, final in sync_body_chunks(self._iterator, self._state.content_length):
            if self._state.cancelled.is_set():
                return
            if final:
                self._final_chunk = chunk
                self._should_finish = True
                return
            if not self._raw_body.send(chunk):
                return
        self._should_finish = not self._state.cancelled.is_set()

    def _complete_body(self) -> None:
        if not self._should_finish:
            return
        try:
            if self._final_chunk is None:
                self._raw_body.finish()
            else:
                self._raw_body.send_final(self._final_chunk)
        except (asyncio.CancelledError, Exception) as error:  # noqa: BLE001
            self._report_error(error)
        except BaseException as error:  # noqa: BLE001
            with suppress(BaseException):
                self._raw_body.close()
            self._primary_error = error
            self._state.publish(error)

    def _report_error(self, error: BaseException) -> None:
        if self._state.cancelled.is_set():
            return
        try:
            self._raw_body.fail(upload_error_message(error))
        except BaseException as report_error:  # noqa: BLE001
            with suppress(BaseException):
                self._raw_body.close()
            self._primary_error = report_error
            self._state.publish(report_error)
        else:
            self._source_error_reported = True

    def _close_sources(self) -> None:
        try:
            _close_sync_sources(self._iterator, self._source, self._source_cleanup)
        except BaseException as error:  # noqa: BLE001
            if self._primary_error is None and not self._source_error_reported:
                with suppress(BaseException):
                    self._raw_body.close()
                self._primary_error = error


class _AsyncUploadFeeder:
    def __init__(
        self,
        raw_body: "_foghttp.RawUploadBody",
        source: object,
        source_cleanup: UploadSourceCleanup,
        ready: asyncio.Event,
        feeder_state: UploadFeederState,
    ) -> None:
        self._raw_body = raw_body
        self._source = source
        self._source_cleanup = source_cleanup
        self._ready = ready
        self._state = feeder_state
        self._iterator: AsyncIterator[object] | None = None
        self._final_chunk: bytes | None = None
        self._should_finish = False
        self._source_error_reported = False

    async def run(self) -> None:
        control_error = await self._feed()
        if control_error is not None:
            self._state.publish(control_error)
            self._raw_body.close()
            await suppress_async_cleanup_error(
                _close_async_sources(self._iterator, self._source, self._source_cleanup),
            )
            raise control_error
        sources_closed = await self._close_sources()
        if sources_closed and not self._source_error_reported and self._should_finish:
            await self._complete_body()

    async def _feed(self) -> BaseException | None:
        try:
            self._iterator = aiter(cast("AsyncIterable[object]", self._source))
            should_finish, final_chunk = await self._feed_chunks()
            self._should_finish = should_finish
            self._final_chunk = final_chunk
        except BaseException as error:  # noqa: BLE001
            control_error = await handle_async_upload_error(
                self._raw_body,
                self._ready,
                error,
                task_is_cancelling=current_task_is_cancelling(),
            )
            self._source_error_reported = control_error is None
            return control_error
        return None

    async def _feed_chunks(self) -> tuple[bool, bytes | None]:
        async for chunk, final in async_body_chunks(self._iterator, self._state.content_length):
            if final:
                return True, chunk
            if not await send_async_upload_chunk(self._raw_body, self._ready, chunk):
                return False, None
        return True, None

    async def _close_sources(self) -> bool:
        try:
            await _close_async_sources(self._iterator, self._source, self._source_cleanup)
        except BaseException as error:
            if current_task_is_cancelling():
                self._raw_body.close()
                raise asyncio.CancelledError from None
            if self._source_error_reported:
                return False
            self._raw_body.close()
            self._state.publish(error)
            raise
        return True

    async def _complete_body(self) -> None:
        try:
            if self._final_chunk is None:
                self._raw_body.finish()
            else:
                await send_async_upload_chunk(
                    self._raw_body,
                    self._ready,
                    self._final_chunk,
                    final=True,
                )
        except BaseException as error:  # noqa: BLE001
            control_error = await handle_async_upload_error(
                self._raw_body,
                self._ready,
                error,
                task_is_cancelling=current_task_is_cancelling(),
            )
            if control_error is None:
                return
            self._raw_body.close()
            self._state.publish(control_error)
            raise control_error from None


def feed_sync_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    source_cleanup: UploadSourceCleanup,
    feeder_state: UploadFeederState,
) -> None:
    _SyncUploadFeeder(raw_body, source, source_cleanup, feeder_state).run()


async def feed_async_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    source_cleanup: UploadSourceCleanup,
    ready: asyncio.Event,
    feeder_state: UploadFeederState,
) -> None:
    try:
        async_stream = is_async_stream(source)
        if not async_stream:
            await run_sync_upload_feeder(
                lambda: feed_sync_upload_body(
                    raw_body,
                    source,
                    source_cleanup,
                    feeder_state,
                ),
                lambda: _cancel_sync_upload_body(source_cleanup, feeder_state),
                worker_state=feeder_state,
            )
            return
    except BaseException:
        with suppress(BaseException):
            raw_body.close()
        raise
    await _AsyncUploadFeeder(
        raw_body,
        source,
        source_cleanup,
        ready,
        feeder_state,
    ).run()


def _cancel_sync_upload_body(
    source_cleanup: UploadSourceCleanup,
    feeder_state: UploadFeederState,
) -> None:
    feeder_state.cancel()
    source_cleanup.start_async_cleanup(interrupt=True)


def _close_sync_sources(
    iterator: "Iterator[object] | None",
    source: object,
    source_cleanup: UploadSourceCleanup,
) -> None:
    if iterator is None or iterator is source:
        source_cleanup.close()
        return
    iterator_cleanup = UploadSourceCleanup(iterator)
    try:
        iterator_cleanup.close()
    except BaseException:
        with suppress(BaseException):
            source_cleanup.close()
        raise
    source_cleanup.close()


async def _close_async_sources(
    iterator: "AsyncIterator[object] | None",
    source: object,
    source_cleanup: UploadSourceCleanup,
) -> None:
    if iterator is None or iterator is source:
        await source_cleanup.aclose()
        return
    iterator_cleanup = UploadSourceCleanup(iterator)
    await source_cleanup.aclose(after=iterator_cleanup)
