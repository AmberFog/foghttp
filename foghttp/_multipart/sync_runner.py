import asyncio
from collections.abc import Iterator
from concurrent.futures import Future as ConcurrentFuture
from contextvars import Context, copy_context
from queue import SimpleQueue
import threading

from .._upload_body import cleanup as upload_cleanup
from .._upload_body.thread_bridge import consume_future_exception


_ITER_DONE = object()


class SyncIteratorRunner:
    def __init__(self, iterator: Iterator[bytes]) -> None:
        self._closed = False
        self._completion: ConcurrentFuture[None] = ConcurrentFuture()
        self._completion.set_running_or_notify_cancel()
        self._context: Context = copy_context()
        self._iterator = iterator
        self._lock = threading.Lock()
        self._requests: SimpleQueue[ConcurrentFuture[bytes | object] | None] = SimpleQueue()
        self._stop_requested = False
        self._worker_pending = 0
        threading.Thread(target=self._run, daemon=True).start()

    async def next(self) -> bytes | object:
        request: ConcurrentFuture[bytes | object] = ConcurrentFuture()
        with self._lock:
            if self._closed:
                return _ITER_DONE
            self._worker_pending += 1
            self._requests.put(request)
        return await asyncio.wrap_future(request)

    def close(self) -> bool:
        with self._lock:
            pending = self._worker_pending > 0
            if not self._closed and not self._stop_requested:
                self._stop_requested = True
                self._requests.put(None)
        if pending:
            self._completion.add_done_callback(consume_future_exception)
        return pending

    async def wait_closed_bounded(self) -> None:
        completion = asyncio.wrap_future(self._completion)
        completion.add_done_callback(consume_future_exception)
        done, _pending = await asyncio.wait(
            (completion,),
            timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
        )
        if completion in done:
            completion.result()

    def _run(self) -> None:
        try:
            self._consume_requests()
            self._context.run(upload_cleanup.close_sync_source, self._iterator)
        except BaseException as error:  # noqa: BLE001
            self._completion.set_exception(error)
        else:
            self._completion.set_result(None)
        finally:
            with self._lock:
                self._closed = True
                self._worker_pending = 0

    def _consume_requests(self) -> None:
        while (request := self._requests.get()) is not None:
            if not request.set_running_or_notify_cancel():
                self._mark_worker_idle()
                continue
            try:
                chunk = self._context.run(next, self._iterator, _ITER_DONE)
            except BaseException as error:  # noqa: BLE001
                self._mark_worker_idle()
                request.set_exception(error)
                return
            self._mark_worker_idle()
            request.set_result(chunk)
            if chunk is _ITER_DONE:
                return

    def _mark_worker_idle(self) -> None:
        with self._lock:
            self._worker_pending = max(0, self._worker_pending - 1)
