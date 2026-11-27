import asyncio
from concurrent.futures import wait

from . import cleanup as upload_cleanup
from .cleanup_start import defer_worker_interrupts


def prepare_factory_source(
    source_factory: object,
) -> tuple[object, upload_cleanup.UploadSourceCleanup, BaseException | None]:
    reservation = upload_cleanup.reserve_cleanup()
    try:
        source = source_factory()  # type: ignore[operator]
    except BaseException:
        reservation.release()
        raise
    if isinstance(source, upload_cleanup.UploadSourceFactoryFailure):
        return source.source, upload_cleanup.UploadSourceCleanup(source.source, reservation=reservation), source.error
    return source, upload_cleanup.UploadSourceCleanup(source, reservation=reservation), None


@defer_worker_interrupts()
def start_ready_async_cleanups(
    cleanups: list[upload_cleanup.UploadSourceCleanup],
    pending_cleanup_ids: set[int],
) -> tuple[asyncio.Future[None], ...]:
    return tuple(
        task
        for cleanup in cleanups
        if id(cleanup) not in pending_cleanup_ids and (task := cleanup.start_async_cleanup()) is not None
    )


def wait_sync_cleanups(
    cleanups: list[upload_cleanup.UploadSourceCleanup] | tuple[upload_cleanup.UploadSourceCleanup, ...],
) -> BaseException | None:
    with defer_worker_interrupts():
        pending = tuple(
            (cleanup, completion) for cleanup in cleanups if (completion := cleanup.start_sync_cleanup()) is not None
        )
    if not pending:
        return None
    done = wait(
        tuple(completion for cleanup, completion in pending),
        timeout=upload_cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT,
    ).done
    for cleanup, completion in pending:
        if completion in done:
            error = cleanup.consume_sync_error()
            if error is not None:
                return error
    return None
