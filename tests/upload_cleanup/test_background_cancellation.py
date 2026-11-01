import asyncio
from contextlib import suppress

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .cleanup_actions import wait_sync_event
from .constants import COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


async def test_cancelled_background_wrapper_retains_running_sync_callback(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncCloseGate()
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    completion = source_cleanup.start_async_cleanup()
    assert completion is not None
    try:
        assert await wait_sync_event(source.entered)
        completion.cancel()
        with pytest.raises(asyncio.CancelledError):
            await completion

        assert source.finished.is_set() is False
        assert cleanup_owner.cleanup_snapshot()["reserved"] == 1
        assert cleanup_owner.cleanup_snapshot()["active"] == 1
    finally:
        source.release.set()
        await asyncio.wait_for(source_cleanup.aclose(bounded=False), COMPLETION_WATCHDOG)

    assert source.calls == 1
    assert source.finished.is_set() is True
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0


async def test_cancelled_async_callback_releases_only_after_its_finally_finishes(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = AsyncCloseGate()
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    existing_tasks = asyncio.all_tasks()
    completion = source_cleanup.start_async_cleanup()
    assert completion is not None
    try:
        await asyncio.wait_for(source.entered.wait(), COMPLETION_WATCHDOG)
        callback_tasks = asyncio.all_tasks() - existing_tasks
        assert len(callback_tasks) == 1

        callback_tasks.pop().cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(completion), COMPLETION_WATCHDOG)
    finally:
        source.release.set()
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(completion), COMPLETION_WATCHDOG)
    assert source.finished.is_set() is True
    assert source.calls == 1
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
