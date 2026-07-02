import asyncio
from contextlib import suppress
import threading
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable

    from foghttp import _foghttp

from .async_sending import fail_async_upload_body, send_async_upload_chunk
from .chunks import body_chunk
from .file_source import FileUploadSource
from .predicates import is_async_stream
from .thread_bridge import run_sync_upload_feeder


def feed_sync_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    cancelled: threading.Event | None = None,
) -> None:
    is_cancelled = bool if cancelled is None else cancelled.is_set
    try:
        for chunk in cast("Iterable[object]", source):
            if is_cancelled():
                return
            if not raw_body.send(body_chunk(chunk)):
                return
    except Exception as exc:  # noqa: BLE001
        if not is_cancelled():
            raw_body.fail(_upload_source_error(exc))
    else:
        if not is_cancelled():
            raw_body.finish()
    finally:
        close_sync_source(source)


async def feed_async_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    ready: asyncio.Event,
) -> None:
    if not is_async_stream(source):
        cancelled = threading.Event()
        await run_sync_upload_feeder(
            lambda: feed_sync_upload_body(raw_body, source, cancelled),
            lambda: _cancel_sync_upload_body(raw_body, source, cancelled),
        )
        return

    source_closed = False
    try:
        async for chunk in cast("AsyncIterable[object]", source):
            if not await send_async_upload_chunk(
                raw_body,
                ready,
                body_chunk(chunk),
            ):
                return
    except asyncio.CancelledError:
        await close_async_source(source)
        source_closed = True
        raise
    except Exception as exc:  # noqa: BLE001
        await fail_async_upload_body(raw_body, ready, _upload_source_error(exc))
    else:
        raw_body.finish()
    finally:
        if not source_closed:
            await close_async_source(source)


def close_sync_source(source: object) -> None:
    target = source.file if isinstance(source, FileUploadSource) else source
    close = getattr(target, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _cancel_sync_upload_body(
    _raw_body: "_foghttp.RawUploadBody",
    source: object,
    cancelled: threading.Event,
) -> None:
    cancelled.set()
    close_sync_source(source)


async def close_async_source(source: object) -> None:
    aclose = getattr(source, "aclose", None)
    if callable(aclose):
        with suppress(Exception):
            await aclose()
        return
    await asyncio.to_thread(close_sync_source, source)


def _upload_source_error(error: BaseException) -> str:
    message = str(error)
    if message:
        return message
    return error.__class__.__name__
