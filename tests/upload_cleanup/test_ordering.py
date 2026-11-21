import asyncio
from typing import TYPE_CHECKING

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .cleanup_actions import finish_sync_cleanups, wait_sync_event
from .constants import CHAIN_OBLIGATIONS, COMPLETION_WATCHDOG
from .sources import SyncCloseGate


if TYPE_CHECKING:
    from concurrent.futures import Future


def test_sync_iterator_predecessor_retains_both_cleanup_obligations(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)
    completions: list[Future[None]] = []
    try:
        completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)
        assert completion is not None
        completions.append(completion)
        assert iterator.entered.wait(COMPLETION_WATCHDOG)

        assert source.calls == 0
        assert completion.done() is False
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        finish_sync_cleanups([iterator, source], completions)

    assert iterator.calls == 1
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


async def test_cancelled_waiter_does_not_advance_sync_cleanup_chain(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)
    completion = source_cleanup.start_async_cleanup(after=iterator_cleanup)
    assert completion is not None
    try:
        assert await wait_sync_event(iterator.entered)
        waiter = asyncio.create_task(source_cleanup.aclose(after=iterator_cleanup))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        iterator.release.set()
        await asyncio.wait_for(asyncio.shield(completion), COMPLETION_WATCHDOG)

    assert iterator.finished.is_set() is True
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


def test_loop_shutdown_and_switch_retain_actual_sync_predecessor_completion(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    iterator = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)

    async def close_in_loop() -> None:
        await source_cleanup.aclose(after=iterator_cleanup)

    try:
        asyncio.run(close_in_loop())
        assert iterator.entered.wait(COMPLETION_WATCHDOG)
        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS

        asyncio.run(close_in_loop())

        assert source.calls == 0
        assert cleanup_owner.cleanup_snapshot()["reserved"] == CHAIN_OBLIGATIONS
    finally:
        iterator.release.set()
        completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)
        assert completion is not None
        completion.result(timeout=COMPLETION_WATCHDOG)

    assert iterator.finished.is_set() is True
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


@pytest.mark.parametrize(
    "failure",
    [
        GeneratorExit("iterator cleanup control failure"),
        BaseExceptionGroup("iterator cleanup failures", [ValueError("ordinary failure"), GeneratorExit("control")]),
    ],
)
def test_predecessor_control_error_still_closes_source_and_releases_chain(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
    failure: BaseException,
) -> None:
    iterator = SyncCloseGate(blocked=False, error=failure)
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(CHAIN_OBLIGATIONS))
    iterator_cleanup = source_cleanup.iteration.track(iterator)

    completion = source_cleanup.start_sync_cleanup(after=iterator_cleanup)

    assert completion is not None
    with pytest.raises(type(failure)) as observed:
        completion.result(timeout=COMPLETION_WATCHDOG)
    assert observed.value is failure
    assert iterator.calls == 1
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
