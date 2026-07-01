import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import AsyncIterable, Iterable

    from foghttp import _foghttp

from ..messages import STREAMING_BODY_CHUNK_UNSUPPORTED
from .async_sending import fail_async_upload_body, send_async_upload_chunk
from .file_source import FileUploadSource
from .predicates import is_async_stream
from .thread_bridge import run_sync_upload_feeder


def feed_sync_upload_body(raw_body: "_foghttp.RawUploadBody", source: object) -> None:
    try:
        for chunk in cast("Iterable[object]", source):
            if not raw_body.send(_validate_upload_chunk(chunk)):
                return
    except Exception as exc:  # noqa: BLE001
        raw_body.fail(_upload_source_error(exc))
    else:
        raw_body.finish()
    finally:
        close_sync_source(source)


async def feed_async_upload_body(
    raw_body: "_foghttp.RawUploadBody",
    source: object,
    ready: asyncio.Event,
) -> None:
    if not is_async_stream(source):
        await run_sync_upload_feeder(
            lambda: feed_sync_upload_body(raw_body, source),
            lambda: _cancel_sync_upload_body(raw_body, source),
        )
        return

    try:
        async for chunk in cast("AsyncIterable[object]", source):
            if not await send_async_upload_chunk(
                raw_body,
                ready,
                _validate_upload_chunk(chunk),
            ):
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        await fail_async_upload_body(raw_body, ready, _upload_source_error(exc))
    else:
        raw_body.finish()
    finally:
        await close_async_source(source)


def close_sync_source(source: object) -> None:
    target = source.file if isinstance(source, FileUploadSource) else source
    close = getattr(target, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _cancel_sync_upload_body(raw_body: "_foghttp.RawUploadBody", source: object) -> None:
    raw_body.close()
    close_sync_source(source)


async def close_async_source(source: object) -> None:
    aclose = getattr(source, "aclose", None)
    if callable(aclose):
        with suppress(Exception):
            await aclose()
        return
    await asyncio.to_thread(close_sync_source, source)


def _validate_upload_chunk(chunk: object) -> bytes:
    if isinstance(chunk, bytes):
        return chunk
    if isinstance(chunk, bytearray):
        return bytes(chunk)
    if isinstance(chunk, memoryview):
        return chunk.tobytes()
    raise TypeError(STREAMING_BODY_CHUNK_UNSUPPORTED)


def _upload_source_error(error: BaseException) -> str:
    message = str(error)
    if message:
        return message
    return error.__class__.__name__
