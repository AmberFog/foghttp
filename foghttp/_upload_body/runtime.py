import asyncio
from contextlib import suppress
from contextvars import copy_context
from functools import partial
import threading

import foghttp._foghttp as _foghttp  # noqa: PLR0402

from .. import messages
from .._client.process import current_process_id, forked_process_error
from .._request_body import RequestBody
from . import (
    attempt as upload_attempt,
    cleanup as upload_cleanup,
    models as upload_models,
    predicates as upload_predicates,
)
from .feeders import feed_async_upload_body, feed_sync_upload_body
from .thread_bridge import (
    AsyncFeederRunner,
    UploadFeederState,
    consume_future_exception,
)


AsyncFeeder = tuple[
    AsyncFeederRunner,
    UploadFeederState,
    upload_cleanup.UploadSourceCleanup,
]


UPLOAD_FEEDER_JOIN_TIMEOUT = 0.1
ASYNC_UPLOAD_FEEDER_JOIN_TIMEOUT = 1.0


class _SyncStreamingUploadBody:
    def __init__(
        self,
        source: object,
        content_length: int | None,
        *,
        replayable: bool,
        raw_client: _foghttp.RawClient | None = None,
    ) -> None:
        self._created_process_id = current_process_id()
        reservation = None if replayable else upload_cleanup.reserve_cleanup()
        self.buffered_body: bytes | None = None
        try:
            self.raw_body: _foghttp.RawUploadBody | None = _foghttp.RawUploadBody(
                content_length,
                self.start,
                replayable,
                None,
                raw_client=raw_client,
            )
        except BaseException:
            if reservation is not None:
                reservation.release()
            raise
        self._source = source
        self._context = copy_context()
        self._content_length = content_length
        self._source_cleanups = (
            [] if replayable else [upload_cleanup.UploadSourceCleanup(source, reservation=reservation)]
        )
        self._feeder_errors: list[UploadFeederState] = []
        self._threads: list[threading.Thread] = []
        self._lifecycle_lock = threading.Lock()
        self._closed = threading.Event()
        self._replayable = replayable

    def start(self, raw_body: _foghttp.RawUploadBody) -> None:
        if current_process_id() != self._created_process_id:
            raise forked_process_error(
                resource="upload body",
                created_process_id=self._created_process_id,
                current_process_id=current_process_id(),
            )
        if self._closed.is_set():
            raw_body.close()
            return
        attempt_context = self._context.copy()
        source, source_cleanup = attempt_context.run(self._fresh_source)
        if self._closed.is_set():
            raw_body.close()
            return
        if attempt_context.run(upload_predicates.is_async_stream, source):
            attempt_context.run(source_cleanup.aclose_from_sync)
            raise TypeError(messages.SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
        feeder_state = UploadFeederState(self._content_length)
        thread = threading.Thread(
            target=attempt_context.run,
            args=(self._feed_body, raw_body, source, source_cleanup, feeder_state),
            daemon=True,
        )
        if not self._start_feeder(thread, feeder_state, source_cleanup):
            raw_body.close()

    def close(self) -> None:
        if current_process_id() != self._created_process_id:
            return
        with self._lifecycle_lock:
            self._closed.set()
            if self.raw_body is not None:
                self.raw_body.close()
            self.raw_body = None
        for thread in self._threads:
            if threading.current_thread() is not thread:
                thread.join(UPLOAD_FEEDER_JOIN_TIMEOUT)
        for feeder_state in self._feeder_errors:
            feeder_state.cancel()
        source_error = upload_attempt.wait_sync_cleanups(self._source_cleanups)
        feeder_error = next(
            (error for state in self._feeder_errors if (error := state.get()) is not None),
            None,
        )
        if feeder_error is not None:
            raise feeder_error
        if source_error is not None:
            raise source_error

    def _start_feeder(
        self,
        thread: threading.Thread,
        feeder_state: UploadFeederState,
        source_cleanup: upload_cleanup.UploadSourceCleanup,
    ) -> bool:
        with self._lifecycle_lock:
            if self._closed.is_set():
                return False
            source_cleanup.iteration.reserve()
            self._feeder_errors.append(feeder_state)
            self._threads.append(thread)
            try:
                thread.start()
            except BaseException:
                source_cleanup.iteration.release()
                self._threads.remove(thread)
                self._feeder_errors.remove(feeder_state)
                raise
        return True

    def _feed_body(
        self,
        raw_body: _foghttp.RawUploadBody,
        source: object,
        source_cleanup: upload_cleanup.UploadSourceCleanup,
        feeder_state: UploadFeederState,
    ) -> None:
        with self._lifecycle_lock:
            if threading.current_thread() not in self._threads:
                return
        try:
            feed_sync_upload_body(
                raw_body,
                source,
                source_cleanup,
                feeder_state,
            )
        except BaseException as error:  # noqa: BLE001
            feeder_state.publish(error)
        finally:
            source_cleanup.iteration.release()

    def _fresh_source(self) -> tuple[object, upload_cleanup.UploadSourceCleanup]:
        if self._replayable:
            source, source_cleanup, source_error = upload_attempt.prepare_factory_source(self._source)
            registered = self._register_source_cleanup(source_cleanup)
            if not registered:
                source_cleanup.start_sync_cleanup()
            if source_error is not None:
                cleanup_error = upload_attempt.wait_sync_cleanups((source_cleanup,))
                if cleanup_error is not None:
                    raise source_error from cleanup_error
                raise source_error
            return source, source_cleanup
        return self._source, self._source_cleanups[0]

    def _register_source_cleanup(
        self,
        source_cleanup: upload_cleanup.UploadSourceCleanup,
    ) -> bool:
        with self._lifecycle_lock:
            if self._closed.is_set():
                return False
            self._source_cleanups.append(source_cleanup)
            return True


class _AsyncStreamingUploadBody:
    def __init__(
        self,
        source: object,
        content_length: int | None,
        *,
        replayable: bool,
        raw_client: _foghttp.RawClient | None = None,
    ) -> None:
        self._created_process_id = current_process_id()
        self._loop = asyncio.get_running_loop()
        reservation = None if replayable else upload_cleanup.reserve_cleanup()
        self.buffered_body: bytes | None = None
        try:
            self.raw_body: _foghttp.RawUploadBody | None = _foghttp.RawUploadBody(
                content_length,
                self.start,
                replayable,
                self._notify_ready,
                raw_client=raw_client,
            )
        except BaseException:
            if reservation is not None:
                reservation.release()
            raise
        self._source = source
        self._context = copy_context()
        self._content_length = content_length
        self._ready = asyncio.Event()
        self._feeders: list[AsyncFeeder] = []
        self._factory_error: BaseException | None = None
        self._lifecycle_lock = threading.Lock()
        self._closed = threading.Event()
        self._source_cleanups = (
            [] if replayable else [upload_cleanup.UploadSourceCleanup(source, reservation=reservation)]
        )
        self._replayable = replayable

    def start(self, raw_body: _foghttp.RawUploadBody) -> None:
        if current_process_id() != self._created_process_id:
            raise forked_process_error(
                resource="upload body",
                created_process_id=self._created_process_id,
                current_process_id=current_process_id(),
            )
        if self._closed.is_set():
            raw_body.close()
            return
        attempt_context = self._context.copy()
        source, source_cleanup = attempt_context.run(self._fresh_source)
        feeder_state = UploadFeederState(self._content_length)
        runner = AsyncFeederRunner(
            self._loop,
            partial(
                feed_async_upload_body,
                raw_body,
                source,
                source_cleanup,
                self._ready,
                feeder_state,
            ),
        )
        with self._lifecycle_lock:
            if self._closed.is_set():
                raw_body.close()
                return
            source_cleanup.iteration.reserve()
            self._feeders.append((runner, feeder_state, source_cleanup))
        runner.completion.add_done_callback(
            partial(
                _finish_feeder_attempt,
                raw_body,
                source_cleanup,
                feeder_state,
                runner,
            ),
        )
        runner.completion.add_done_callback(consume_future_exception)
        try:
            runner.start(context=attempt_context)
        except BaseException:
            source_cleanup.iteration.release()
            with self._lifecycle_lock, suppress(ValueError):
                self._feeders.remove((runner, feeder_state, source_cleanup))
            raise

    async def aclose(self) -> None:
        if current_process_id() != self._created_process_id:
            return
        with self._lifecycle_lock:
            self._closed.set()
        if self.raw_body is not None:
            self.raw_body.close()
        self.raw_body = None
        for pending in self._feeders:
            pending[1].cancel()
            if not pending[0].completion.done():
                pending[0].cancel()
        feeder_error = None
        drain_error = None
        try:
            feeder_error = await self._drain_futures()
        except BaseException as error:  # noqa: BLE001
            drain_error = error
        pending_cleanup_ids = _pending_cleanup_ids(self._feeders)
        for source_cleanup in self._source_cleanups:
            if id(source_cleanup) not in pending_cleanup_ids:
                source_cleanup.start_async_cleanup()
        if drain_error is not None:
            raise drain_error
        await self._close_sources(feeder_error, pending_cleanup_ids)

    def _fresh_source(self) -> tuple[object, upload_cleanup.UploadSourceCleanup]:
        if self._replayable:
            source, source_cleanup, source_error = upload_attempt.prepare_factory_source(self._source)
            with self._lifecycle_lock:
                if self._closed.is_set():
                    registered = False
                else:
                    self._source_cleanups.append(source_cleanup)
                    registered = True
            if not registered:
                source_cleanup.start_sync_cleanup()
            if source_error is not None:
                self._factory_error = source_error
                raise source_error
            return source, source_cleanup
        return self._source, self._source_cleanups[0]

    async def _close_sources(
        self,
        feeder_error: BaseException | None,
        pending_cleanup_ids: set[int],
    ) -> None:
        tasks = tuple(
            filter(
                None,
                map(
                    upload_cleanup.UploadSourceCleanup.start_async_cleanup,
                    [
                        source_cleanup
                        for source_cleanup in self._source_cleanups
                        if id(source_cleanup) not in pending_cleanup_ids
                    ],
                ),
            ),
        )
        done: set[asyncio.Future[None]] = set()
        if tasks:
            done.update(
                (
                    await asyncio.wait(
                        tasks,
                        timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
                    )
                )[0],
            )
        source_error = next(
            (
                error
                for error in map(
                    consume_future_exception,
                    filter(done.__contains__, tasks),
                )
                if error is not None
            ),
            None,
        )
        feeder_errors = (feeder[1].get() for feeder in self._feeders)
        feeder_error = next(
            (error for error in feeder_errors if error is not None),
            feeder_error,
        )
        if upload_cleanup.current_task_is_cancelling(propagating_only=True):
            return
        if self._factory_error is not None:
            if source_error is not None and source_error is not self._factory_error:
                self._factory_error.__cause__ = source_error
            return
        if feeder_error is not None:
            raise feeder_error
        if source_error is not None:
            raise source_error

    async def _drain_futures(self) -> BaseException | None:
        if not self._feeders:
            return None
        futures = tuple(asyncio.wrap_future(feeder[0].completion) for feeder in self._feeders)
        for future in futures:
            future.add_done_callback(consume_future_exception)
        await asyncio.wait(futures, timeout=ASYNC_UPLOAD_FEEDER_JOIN_TIMEOUT)
        for future in futures:
            if future.done() and not future.cancelled():
                error = future.exception()
                if error is not None:
                    return error
        return None

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


def prepare_sync_upload_body(
    body: RequestBody,
    *,
    raw_client: _foghttp.RawClient | None = None,
) -> upload_models.SyncUploadBody:
    if body.stream is None:
        return upload_models.BufferedUploadBody(body.content)
    if upload_predicates.is_async_stream(body.stream):
        raise TypeError(messages.SYNC_CLIENT_ASYNC_BODY_UNSUPPORTED)
    return _SyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
        raw_client=raw_client,
    )


def prepare_async_upload_body(
    body: RequestBody,
    *,
    raw_client: _foghttp.RawClient | None = None,
) -> upload_models.AsyncUploadBody:
    if body.stream is None:
        return upload_models.BufferedUploadBody(body.content)
    return _AsyncStreamingUploadBody(
        body.stream,
        body.content_length,
        replayable=body.replayable,
        raw_client=raw_client,
    )


def _pending_cleanup_ids(feeders: list[AsyncFeeder]) -> set[int]:
    pending_cleanup_ids: set[int] = set()
    for runner, state, source_cleanup in feeders:
        if not runner.completion.done() or state.worker_pending():
            pending_cleanup_ids.add(id(source_cleanup))
    return pending_cleanup_ids


def _finish_feeder_attempt(
    raw_body: _foghttp.RawUploadBody,
    source_cleanup: upload_cleanup.UploadSourceCleanup,
    feeder_state: UploadFeederState,
    runner: AsyncFeederRunner,
    _completion: object,
) -> None:
    if not runner.task_started:
        source_cleanup.iteration.release()
        with suppress(BaseException):
            raw_body.close()
    if not feeder_state.worker_pending():
        source_cleanup.iteration.release()
        source_cleanup.start_async_cleanup()
