import asyncio
import threading
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable

    from foghttp import _foghttp

from .async_sending import fail_async_upload_body, send_async_upload_chunk
from .chunks import body_chunk
from .cleanup import UploadSourceCleanup, current_task_is_cancelling
from .predicates import is_async_stream
from .thread_bridge import run_sync_upload_feeder


def feed_sync_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    source_cleanup: UploadSourceCleanup,
    cancelled: threading.Event | None = None,
) -> None:
    is_cancelled = bool if cancelled is None else cancelled.is_set
    try:
        for chunk in cast("Iterable[object]", source):
            if is_cancelled():
                return
            if not raw_body.send(body_chunk(chunk)):
                return
    except (asyncio.CancelledError, Exception) as exc:  # noqa: BLE001
        if not is_cancelled():
            raw_body.fail(_upload_source_error(exc))
    else:
        if not is_cancelled():
            raw_body.finish()
    finally:
        source_cleanup.close()


async def feed_async_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    source_cleanup: UploadSourceCleanup,
    ready: asyncio.Event,
) -> None:
    if not is_async_stream(source):
        cancelled = threading.Event()
        await run_sync_upload_feeder(
            lambda: feed_sync_upload_body(raw_body, source, source_cleanup, cancelled),
            lambda: _cancel_sync_upload_body(source_cleanup, cancelled),
        )
        return

    try:
        async for chunk in cast("AsyncIterable[object]", source):
            if not await send_async_upload_chunk(
                raw_body,
                ready,
                body_chunk(chunk),
            ):
                return
    except asyncio.CancelledError as exc:
        if current_task_is_cancelling():
            raise
        await fail_async_upload_body(raw_body, ready, _upload_source_error(exc))
    except Exception as exc:  # noqa: BLE001
        await fail_async_upload_body(raw_body, ready, _upload_source_error(exc))
    else:
        raw_body.finish()
    finally:
        await source_cleanup.aclose()


def _cancel_sync_upload_body(
    source_cleanup: UploadSourceCleanup,
    cancelled: threading.Event,
) -> None:
    cancelled.set()
    source_cleanup.start_async_cleanup()


def _upload_source_error(error: BaseException) -> str:
    message = str(error)
    if message:
        return message
    return error.__class__.__name__
