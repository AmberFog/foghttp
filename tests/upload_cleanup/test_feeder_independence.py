import asyncio
import threading

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp._upload_body.thread_bridge import run_sync_upload_feeder

from .cleanup_actions import wait_sync_event
from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


async def test_blocked_feeder_does_not_consume_releasing_cleanup_worker(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    feeder = SyncCloseGate()
    source = SyncCloseGate(blocked=False)
    feeder_task = asyncio.create_task(run_sync_upload_feeder(feeder.close))
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    try:
        assert await wait_sync_event(feeder.entered)

        await asyncio.wait_for(source_cleanup.aclose(), COMPLETION_WATCHDOG)

        assert await wait_sync_event(source.finished)
        assert source.calls == 1
        assert source.thread_id != threading.get_ident()
        assert feeder.finished.is_set() is False
        assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
    finally:
        feeder.release.set()
        await asyncio.wait_for(feeder_task, COMPLETION_WATCHDOG)
