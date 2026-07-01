import asyncio
from collections.abc import Callable
from contextlib import suppress
import threading


ASYNC_SYNC_FEEDER_CANCEL_TIMEOUT = 1.0


async def run_sync_upload_feeder(
    feeder: Callable[[], None],
    cancel: Callable[[], None],
) -> None:
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()
    thread = threading.Thread(
        target=_run_feeder,
        args=(feeder, loop, done),
        daemon=True,
    )
    thread.start()
    try:
        await asyncio.shield(done)
    except asyncio.CancelledError:
        cancel()
        await _wait_for_cancelled_feeder(done)
        raise


def _run_feeder(
    feeder: Callable[[], None],
    loop: asyncio.AbstractEventLoop,
    done: asyncio.Future[None],
) -> None:
    try:
        feeder()
    except BaseException as exc:  # noqa: BLE001
        loop.call_soon_threadsafe(_set_future_exception, done, exc)
    else:
        loop.call_soon_threadsafe(_set_future_result, done)


def _set_future_result(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


def _set_future_exception(future: asyncio.Future[None], exc: BaseException) -> None:
    if not future.done():
        future.set_exception(exc)


async def _wait_for_cancelled_feeder(done: asyncio.Future[None]) -> None:
    with suppress(Exception):
        await asyncio.wait_for(
            asyncio.shield(done),
            timeout=ASYNC_SYNC_FEEDER_CANCEL_TIMEOUT,
        )
