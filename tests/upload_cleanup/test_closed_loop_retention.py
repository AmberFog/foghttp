import asyncio
import gc
import weakref

from foghttp._upload_body import cleanup, cleanup_owner

from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


def test_finished_sync_cleanup_does_not_retain_provider_on_closed_loop(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncCloseGate()
    source_ref = weakref.ref(source)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    try:
        asyncio.run(source_cleanup.aclose())
        assert source.entered.wait(COMPLETION_WATCHDOG)
        assert source.finished.is_set() is False
        assert cleanup_owner.cleanup_snapshot()["reserved"] == 1
    finally:
        source.release.set()
        completion = source_cleanup.start_sync_cleanup()
        assert completion is not None
        completion.result(timeout=COMPLETION_WATCHDOG)

    # A subsequent job proves the worker has dropped its previous callback frame.
    drained = isolated_cleanup_owner.reserve(1).submit_sync(lambda: None)
    drained.result(timeout=COMPLETION_WATCHDOG)
    del source_cleanup
    del source
    del completion
    gc.collect()

    assert source_ref() is None
    assert cleanup_owner.cleanup_snapshot()["reserved"] == 0
