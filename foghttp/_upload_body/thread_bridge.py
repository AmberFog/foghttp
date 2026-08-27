import asyncio
from collections.abc import Callable, Coroutine, Iterable
from concurrent.futures import (
    Future as ConcurrentFuture,
    wait,
)
from contextlib import suppress
from contextvars import Context, copy_context
import threading
from typing import Any, TypeVar


_FutureResult = TypeVar("_FutureResult")


class UploadFeederState:
    __slots__ = ("_error", "_lock", "_worker_completion", "cancelled", "content_length")

    def __init__(self, content_length: int | None = None) -> None:
        self._error: BaseException | None = None
        self._lock = threading.Lock()
        self._worker_completion: ConcurrentFuture[Any] | None = None
        self.cancelled = threading.Event()
        self.content_length = content_length

    def publish(self, error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            return
        with self._lock:
            if self._error is None and not self.cancelled.is_set():
                self._error = error

    def cancel(self) -> None:
        with self._lock:
            self.cancelled.set()

    def get(self) -> BaseException | None:
        with self._lock:
            return self._error

    def track_worker(self, completion: ConcurrentFuture[Any]) -> None:
        with self._lock:
            self._worker_completion = completion

    def worker_pending(self) -> bool:
        with self._lock:
            return self._worker_completion is not None and not self._worker_completion.done()


class AsyncFeederRunner:
    __slots__ = (
        "_cancel_requested",
        "_feeder",
        "_lock",
        "_loop",
        "_task",
        "completion",
        "task_started",
    )

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        feeder: Callable[[], Coroutine[object, object, None]],
    ) -> None:
        self._loop = loop
        self._feeder = feeder
        self._lock = threading.Lock()
        self._task: asyncio.Task[None] | None = None
        self._cancel_requested = False
        self.completion: ConcurrentFuture[None] = ConcurrentFuture()
        self.task_started = False

    def start(self, *, context: Context | None = None) -> None:
        self._loop.call_soon_threadsafe(self._start, context=context)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            task = self._task
        if task is not None:
            self._loop.call_soon_threadsafe(task.cancel)

    def _start(self) -> None:
        feeder = self._feeder()
        try:
            task = asyncio.create_task(feeder)
        except BaseException as error:  # noqa: BLE001
            feeder.close()
            self.completion.set_exception(error)
            return
        self.task_started = True
        with self._lock:
            self._task = task
            cancel_requested = self._cancel_requested
        task.add_done_callback(self._finish)
        if cancel_requested:
            task.cancel()

    def _finish(self, task: asyncio.Task[None]) -> None:
        with self._lock:
            self._task = None
        if self.completion.done():
            return
        if task.cancelled():
            self.completion.cancel()
            return
        error = task.exception()
        if error is not None:
            self.completion.set_exception(error)
            return
        self.completion.set_result(None)


async def run_sync_in_daemon(
    callback: Callable[[], _FutureResult],
    cancel: Callable[[], None] | None = None,
    *,
    worker_state: UploadFeederState | None = None,
) -> _FutureResult:
    completion = start_daemon_worker(callback)
    if worker_state:
        worker_state.track_worker(completion)
    done = asyncio.wrap_future(completion)
    done.add_done_callback(consume_future_exception)
    try:
        await asyncio.wait((done,))
        return done.result()
    except asyncio.CancelledError:
        if cancel is not None:
            cancel()
        raise
    except BaseException:
        task = asyncio.current_task()
        if cancel is None or task is None or not task.cancelling():
            raise
        cancel()
        raise asyncio.CancelledError from None


run_sync_upload_feeder = run_sync_in_daemon


def run_daemon_callbacks_bounded(
    callbacks: Iterable[Callable[[], None]],
    *,
    timeout: float,
) -> BaseException | None:
    completions = tuple(start_daemon_worker(callback, capture_start_error=True) for callback in callbacks)
    for completion in completions:
        completion.add_done_callback(consume_future_exception)
    done, _pending = wait(completions, timeout=timeout)
    for completion in completions:
        if completion not in done:
            continue
        error = consume_future_exception(completion)
        if error is not None:
            return error
    return None


def start_daemon_worker(
    callback: Callable[[], _FutureResult],
    *,
    capture_start_error: bool = False,
) -> ConcurrentFuture[_FutureResult]:
    completion: ConcurrentFuture[_FutureResult] = ConcurrentFuture()
    context = copy_context()
    thread = threading.Thread(
        target=_run_daemon_worker,
        args=(callback, context, completion),
        daemon=True,
    )
    try:
        thread.start()
    except Exception as error:
        if not capture_start_error:
            raise
        completion.set_exception(error)
    return completion


def _run_daemon_worker(
    callback: Callable[[], _FutureResult],
    context: Context,
    completion: ConcurrentFuture[_FutureResult],
) -> None:
    try:
        result = context.run(callback)
    except BaseException as error:  # noqa: BLE001
        completion.set_exception(error)
    else:
        completion.set_result(result)


def consume_future_exception(
    future: asyncio.Future[_FutureResult] | ConcurrentFuture[_FutureResult],
    *,
    callback: Callable[[], None] | None = None,
) -> BaseException | None:
    try:
        future_error = future.exception()
    except BaseException as error:  # noqa: BLE001
        future_error = error
    if callback is not None:
        with suppress(BaseException):
            callback()
    return future_error
