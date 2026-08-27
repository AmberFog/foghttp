from __future__ import annotations

import asyncio
from contextvars import Context, copy_context
import sys
import threading

from .file_source import FileUploadSource
from .thread_bridge import (
    consume_future_exception,
    run_sync_in_daemon,
    start_daemon_worker,
)


ASYNC_SOURCE_CLOSE_TIMEOUT = 1.0
_BACKGROUND_ASYNC_CLEANUPS: set[asyncio.Task[None]] = set()  # noqa: WPS407


class UploadSourceCleanup:
    __slots__ = (
        "_async_cleanup",
        "_claimed",
        "_context",
        "_interrupt_finished",
        "_lock",
        "_source",
    )

    def __init__(self, source: object, *, context: Context | None = None) -> None:
        self._source = source
        self._async_cleanup: asyncio.Task[None] | None = None
        self._claimed = False
        self._context = copy_context() if context is None else context.copy()
        self._interrupt_finished = threading.Event()
        self._interrupt_finished.set()
        self._lock = threading.Lock()

    def close(self) -> None:
        if not self._interrupt_finished.wait(ASYNC_SOURCE_CLOSE_TIMEOUT):
            return
        with self._lock:
            if not self._interrupt_finished.is_set() or self._claimed:
                return
            self._claimed = True
        started = self._context.copy().run(close_sync_source, self._source)
        if not started:
            with self._lock:
                self._claimed = False

    async def aclose(
        self,
        *,
        after: UploadSourceCleanup | None = None,
        bounded: bool = True,
    ) -> None:
        task = self._get_or_create_async_cleanup(after)
        if task is not None:
            timeout = ASYNC_SOURCE_CLOSE_TIMEOUT if bounded else None
            done, _pending = await asyncio.wait((task,), timeout=timeout)
            if task in done:
                task.result()

    def start_async_cleanup(
        self,
        *,
        interrupt: bool = False,
        after: UploadSourceCleanup | None = None,
    ) -> asyncio.Task[None] | None:
        if interrupt:
            cleanup = run_sync_in_daemon(self.interrupt)
            try:
                task = asyncio.create_task(
                    cleanup,
                    context=self._context.copy(),
                )
            except BaseException as error:
                cleanup.close()
                if isinstance(error, Exception):
                    return None
                raise
            _BACKGROUND_ASYNC_CLEANUPS.add(task)
            task.add_done_callback(_BACKGROUND_ASYNC_CLEANUPS.discard)
            task.add_done_callback(consume_future_exception)
            return task
        return self._get_or_create_async_cleanup(after)

    def aclose_from_sync(self) -> None:
        with self._lock:
            if self._claimed:
                return
            self._claimed = True
        started, error = self._context.copy().run(close_async_source_from_sync, self._source)
        if not started:
            with self._lock:
                self._claimed = False
        if error is not None and not isinstance(error, Exception):
            raise error

    def interrupt(self) -> None:
        with self._lock:
            if self._claimed:
                return
            self._claimed = True
            self._interrupt_finished.clear()
        try:
            started = self._context.copy().run(close_sync_source, self._source)
        except BaseException:
            self._interrupt_finished.set()
            raise
        with self._lock:
            if not started:
                self._claimed = False
            self._interrupt_finished.set()

    def _get_or_create_async_cleanup(
        self,
        after: UploadSourceCleanup | None = None,
    ) -> asyncio.Task[None] | None:
        with self._lock:
            if self._async_cleanup is not None:
                return self._async_cleanup
            if self._claimed:
                return None
            self._claimed = True
            cleanup = (
                close_async_source(self._source) if after is None else close_async_source_after(after, self._source)
            )
            try:
                task = asyncio.create_task(
                    cleanup,
                    context=self._context.copy(),
                )
            except BaseException as error:
                cleanup.close()
                self._claimed = False
                if isinstance(error, Exception):
                    return None
                raise
            self._async_cleanup = task
            _BACKGROUND_ASYNC_CLEANUPS.add(self._async_cleanup)
            self._async_cleanup.add_done_callback(_BACKGROUND_ASYNC_CLEANUPS.discard)
            self._async_cleanup.add_done_callback(consume_future_exception)
            return self._async_cleanup


class UploadSourceFactoryFailure:
    __slots__ = ("error", "source")

    def __init__(self, source: object, error: BaseException) -> None:
        self.source = source
        self.error = error


def close_sync_source(source: object) -> bool:
    try:
        target = source.file if isinstance(source, FileUploadSource) else source
        close = getattr(target, "close", None)
        if callable(close):
            close()
            return True
        aclose = getattr(target, "aclose", None)
    except Exception:  # noqa: BLE001
        return True
    if not callable(aclose):
        return True
    started, error = close_async_source_from_sync(target)
    if error is None or isinstance(error, Exception):
        return started
    raise error


async def close_async_source(source: object) -> None:
    try:
        target = source.file if isinstance(source, FileUploadSource) else source
        aclose = getattr(target, "aclose", None)
        if callable(aclose):
            await aclose()
        else:
            await run_sync_in_daemon(lambda: close_sync_source(source))
    except asyncio.CancelledError:
        if current_task_is_cancelling():
            raise
    except Exception:  # noqa: BLE001
        return


async def close_async_source_after(
    first: UploadSourceCleanup,
    source: object,
) -> None:
    first_error: BaseException | None = None
    source_error: BaseException | None = None
    try:
        await first.aclose(bounded=False)
    except BaseException as error:  # noqa: BLE001
        first_error = error
    try:
        await close_async_source(source)
    except BaseException as error:  # noqa: BLE001
        source_error = error
    cleanup_error = first_error or source_error
    if cleanup_error is None:
        return
    raise cleanup_error


def close_async_source_from_sync(source: object) -> tuple[bool, BaseException | None]:
    try:
        completion = start_daemon_worker(
            lambda: asyncio.run(close_async_source(source)),
        )
    except BaseException as error:  # noqa: BLE001
        return False, error
    completion.add_done_callback(consume_future_exception)
    try:
        completion.result(timeout=ASYNC_SOURCE_CLOSE_TIMEOUT)
    except TimeoutError:
        return True, None
    except BaseException as error:  # noqa: BLE001
        return True, error
    return True, None


def current_task_is_cancelling(*, propagating_only: bool = False) -> bool:
    if propagating_only:
        return isinstance(sys.exception(), asyncio.CancelledError)
    current_task = asyncio.current_task()
    return current_task is not None and bool(current_task.cancelling())
