import asyncio
import json
import sys
import threading
import time

from foghttp._upload_body import cleanup, cleanup_owner
from foghttp.errors import LifecycleError

from .constants import CHAIN_OBLIGATIONS, CLOSE_WAIT, COMPLETION_WATCHDOG
from .sources import AsyncCloseGate, SyncCloseGate


def observe_closed_loop_cleanup() -> dict[str, object]:
    owner = cleanup_owner.CleanupOwner(max_active=1, max_obligations=CHAIN_OBLIGATIONS)
    cleanup.ASYNC_SOURCE_CLOSE_TIMEOUT = CLOSE_WAIT
    sync_source = SyncCloseGate()
    async_source = AsyncCloseGate()
    sync_cleanup = cleanup.UploadSourceCleanup(sync_source, reservation=owner.reserve(1))
    async_cleanup = cleanup.UploadSourceCleanup(async_source, reservation=owner.reserve(1))
    completion = sync_cleanup.start_sync_cleanup()
    if completion is None or not sync_source.entered.wait(COMPLETION_WATCHDOG):
        message = "sync predecessor did not enter before watchdog"
        raise RuntimeError(message)

    async def submit_async_cleanup() -> None:
        async_cleanup.start_async_cleanup()

    try:
        asyncio.run(submit_async_cleanup())
        before_release = owner.snapshot()
    finally:
        sync_source.release.set()
        completion.result(timeout=COMPLETION_WATCHDOG)
    stalled = _wait_for_stalled(owner)
    asyncio.run(async_cleanup.aclose())
    after_loop_switch = owner.snapshot()
    rejected = False
    try:
        unused = owner.reserve(CHAIN_OBLIGATIONS)
    except LifecycleError:
        rejected = True
    else:
        unused.release()
    recovery = SyncCloseGate(blocked=False)
    recovery_cleanup = cleanup.UploadSourceCleanup(recovery, reservation=owner.reserve(1))
    recovered = recovery_cleanup.start_sync_cleanup()
    if recovered is None:
        message = "remaining admitted capacity did not start sync cleanup"
        raise RuntimeError(message)
    recovered.result(timeout=COMPLETION_WATCHDOG)
    return {
        "before_release": before_release,
        "after_release": stalled,
        "after_loop_switch": after_loop_switch,
        "final_snapshot": owner.snapshot(),
        "async_close_calls": async_source.calls,
        "oversized_admission_rejected": rejected,
        "sync_recovery_calls": recovery.calls,
    }


def _wait_for_stalled(owner: cleanup_owner.CleanupOwner) -> dict[str, int]:
    deadline = time.monotonic() + COMPLETION_WATCHDOG
    waiter = threading.Event()
    while time.monotonic() < deadline:
        snapshot = owner.snapshot()
        if snapshot["stalled"]:
            return snapshot
        waiter.wait(CLOSE_WAIT)
    message = "closed-loop cleanup did not reach retained stalled state before watchdog"
    raise RuntimeError(message)


if __name__ == "__main__":
    sys.stdout.write(json.dumps(observe_closed_loop_cleanup()))
