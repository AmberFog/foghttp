import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp.errors import LifecycleError

from .cleanup_actions import finish_sync_cleanups, wait_sync_event
from .constants import COMPLETION_WATCHDOG, OBLIGATION_LIMIT
from .sources import AsyncCloseGate, SyncCloseGate


if TYPE_CHECKING:
    from concurrent.futures import Future


def test_blocked_sync_cleanup_caps_active_and_pending_and_recovers(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    sources = [SyncCloseGate() for _index in range(OBLIGATION_LIMIT)]
    cleanups = [
        cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1)) for source in sources
    ]
    completions: list[Future[None]] = []
    try:
        for source_cleanup in cleanups:
            completion = source_cleanup.start_sync_cleanup()
            assert completion is not None
            completions.append(completion)
        assert sources[0].entered.wait(COMPLETION_WATCHDOG)

        snapshot = cleanup_owner.cleanup_snapshot()
        assert snapshot["reserved"] == OBLIGATION_LIMIT
        assert snapshot["active"] == 1
        assert snapshot["pending"] == OBLIGATION_LIMIT - 1
        assert snapshot["workers"] == 1
        with pytest.raises(LifecycleError):
            isolated_cleanup_owner.reserve(1)
        assert sum(source.calls for source in sources) == 1
    finally:
        finish_sync_cleanups(sources, completions)

    recovery = SyncCloseGate(blocked=False)
    recovered_cleanup = cleanup.UploadSourceCleanup(recovery, reservation=isolated_cleanup_owner.reserve(1))
    recovered = recovered_cleanup.start_sync_cleanup()
    assert recovered is not None
    recovered.result(timeout=COMPLETION_WATCHDOG)
    assert recovery.calls == 1
    assert all(source.calls == 1 for source in sources)
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


async def test_blocked_async_cleanup_bounds_pending_and_survives_waiter_cancellation(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    sources = [AsyncCloseGate() for _index in range(OBLIGATION_LIMIT)]
    cleanups = [
        cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1)) for source in sources
    ]
    completions: list[asyncio.Future[None]] = []
    try:
        for source_cleanup in cleanups:
            completion = source_cleanup.start_async_cleanup()
            assert completion is not None
            completions.append(completion)
        await asyncio.wait_for(sources[0].entered.wait(), COMPLETION_WATCHDOG)
        await asyncio.wait_for(cleanups[0].aclose(), COMPLETION_WATCHDOG)

        waiter = asyncio.create_task(cleanups[0].aclose())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

        snapshot = cleanup_owner.cleanup_snapshot()
        assert snapshot["reserved"] == OBLIGATION_LIMIT
        assert snapshot["active"] == 1
        assert snapshot["pending"] == OBLIGATION_LIMIT - 1
        with pytest.raises(LifecycleError):
            isolated_cleanup_owner.reserve(1)
        assert sum(source.calls for source in sources) == 1
    finally:
        for source in sources:
            source.release.set()
        await asyncio.wait_for(asyncio.gather(*completions), COMPLETION_WATCHDOG)

    assert all(source.calls == 1 for source in sources)
    assert all(source.finished.is_set() for source in sources)
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


async def test_sync_cleanup_runs_off_event_loop_thread(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    loop_thread = threading.get_ident()

    await asyncio.wait_for(source_cleanup.aclose(), COMPLETION_WATCHDOG)

    assert await wait_sync_event(source.finished)
    assert source.thread_id != loop_thread
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
