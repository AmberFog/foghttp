from __future__ import annotations

import asyncio
from functools import partial
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

from .file_source import FileUploadSource


def close_sync_source(source: object) -> None:
    try:
        target = source.file if isinstance(source, FileUploadSource) else source
        close = getattr(target, "close", None)
        if callable(close):
            close()
        else:
            aclose = getattr(target, "aclose", None)
            if callable(aclose):
                asyncio.run(_await_source_close(aclose))
    except Exception:  # noqa: BLE001
        return


def close_async_source_from_sync(source: object) -> None:
    callback = source_async_close(source)
    if callback is None:
        close_sync_source(source)
    else:
        asyncio.run(callback())


def source_async_close(source: object) -> Callable[[], Coroutine[object, object, None]] | None:
    try:
        target = source.file if isinstance(source, FileUploadSource) else source
        aclose = getattr(target, "aclose", None)
    except Exception:  # noqa: BLE001
        return _empty_async_close
    except BaseException as error:  # noqa: BLE001
        return partial(_raise_async_close, error)
    if callable(aclose):
        return lambda: _await_source_close(aclose)
    return None


def current_task_is_cancelling(*, propagating_only: bool = False) -> bool:
    if propagating_only:
        return isinstance(sys.exception(), asyncio.CancelledError)
    current_task = asyncio.current_task()
    return current_task is not None and bool(current_task.cancelling())


async def _await_source_close(aclose: Callable[[], Awaitable[None]]) -> None:
    try:
        await aclose()
    except asyncio.CancelledError:
        if current_task_is_cancelling():
            raise
    except Exception:  # noqa: BLE001
        return


async def _empty_async_close() -> None:
    """Represent a suppressed close-attribute lookup failure."""


async def _raise_async_close(error: BaseException) -> None:
    raise error
