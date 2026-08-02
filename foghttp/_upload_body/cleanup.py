import asyncio
from contextlib import suppress
import threading

from .file_source import FileUploadSource
from .thread_bridge import run_sync_in_daemon


ASYNC_SOURCE_CLOSE_TIMEOUT = 1.0


class UploadSourceCleanup:
    __slots__ = ("_async_cleanup", "_claimed", "_lock", "_source")

    def __init__(self, source: object) -> None:
        self._source = source
        self._async_cleanup: asyncio.Task[None] | None = None
        self._claimed = False
        self._lock = threading.Lock()

    def close(self) -> None:
        if self._claim():
            close_sync_source(self._source)

    async def aclose(self) -> None:
        task = self._get_or_create_async_cleanup()
        if task is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=ASYNC_SOURCE_CLOSE_TIMEOUT,
                )

    def start_async_cleanup(self) -> None:
        self._get_or_create_async_cleanup()

    def aclose_from_sync(self) -> None:
        if self._claim():
            close_async_source_from_sync(self._source)

    def _claim(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True

    def _get_or_create_async_cleanup(self) -> asyncio.Task[None] | None:
        with self._lock:
            if self._async_cleanup is not None:
                return self._async_cleanup
            if self._claimed:
                return None
            self._claimed = True
            self._async_cleanup = asyncio.create_task(close_async_source(self._source))
            return self._async_cleanup


class UploadSourceFactoryFailure:
    __slots__ = ("error", "source")

    def __init__(self, source: object, error: BaseException) -> None:
        self.source = source
        self.error = error


def close_sync_source(source: object) -> None:
    target = source.file if isinstance(source, FileUploadSource) else source
    close = getattr(target, "close", None)
    if callable(close):
        with suppress(Exception):
            close()
        return
    aclose = getattr(target, "aclose", None)
    if callable(aclose):
        close_async_source_from_sync(target)


async def close_async_source(source: object) -> None:
    target = source.file if isinstance(source, FileUploadSource) else source
    aclose = getattr(target, "aclose", None)
    if callable(aclose):
        try:
            await aclose()
        except asyncio.CancelledError:
            if current_task_is_cancelling():
                raise
        except Exception:  # noqa: BLE001
            return
        return
    await run_sync_in_daemon(lambda: close_sync_source(source))


def close_async_source_from_sync(source: object) -> None:
    thread = threading.Thread(
        target=_run_async_source_cleanup,
        args=(source,),
        daemon=True,
    )
    thread.start()
    thread.join(ASYNC_SOURCE_CLOSE_TIMEOUT)


def _run_async_source_cleanup(source: object) -> None:
    asyncio.run(close_async_source(source))


def current_task_is_cancelling() -> bool:
    current_task = asyncio.current_task()
    return current_task is not None and bool(current_task.cancelling())
