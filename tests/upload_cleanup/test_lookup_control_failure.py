import asyncio
import threading

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .constants import COMPLETION_WATCHDOG
from .lookup_sources import ControlLookupSource
from .sources import SyncCloseGate


def test_async_cleanup_without_running_loop_can_be_retried_after_loop_starts(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = SyncCloseGate(blocked=False)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))

    assert source_cleanup.start_async_cleanup() is None
    assert source.calls == 0
    assert isolated_cleanup_owner.snapshot()["reserved"] == 1
    asyncio.run(source_cleanup.aclose(bounded=False))

    assert source.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_control_lookup_failure_is_recorded_once_and_returns_capacity(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    error = GeneratorExit("close lookup control failure")
    source = ControlLookupSource(error)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))

    for _attempt in range(2):
        with pytest.raises(GeneratorExit) as failure:
            await source_cleanup.aclose(bounded=False)
        assert failure.value is error

    assert source.lookups == 1
    assert source_cleanup.completion.exception() is error
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
    recovery = SyncCloseGate(blocked=False)
    recovered = isolated_cleanup_owner.reserve(1).submit_sync(recovery.close)
    recovered.result(timeout=COMPLETION_WATCHDOG)
    assert recovery.calls == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0


async def test_concurrent_loop_cleanup_claims_lookup_once_before_job_submission(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    error = GeneratorExit("concurrent close lookup control failure")
    source = ControlLookupSource(error, gated=True)
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    first_errors: list[BaseException] = []

    async def first_waiter() -> None:
        try:
            await source_cleanup.aclose(bounded=False)
        except BaseException as caught:  # noqa: BLE001
            first_errors.append(caught)

    worker = threading.Thread(target=lambda: asyncio.run(first_waiter()), daemon=True)
    worker.start()
    try:
        assert await asyncio.to_thread(source.entered.wait, COMPLETION_WATCHDOG)
        second_waiter = source_cleanup.start_async_cleanup()
        assert second_waiter is not None
        assert second_waiter.done() is False
        assert source.lookups == 1
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        source.release.set()
        with pytest.raises(GeneratorExit) as failure:
            await asyncio.wait_for(second_waiter, COMPLETION_WATCHDOG)
        assert failure.value is error
    finally:
        source.release.set()
        await asyncio.to_thread(worker.join, COMPLETION_WATCHDOG)

    assert worker.is_alive() is False
    assert first_errors == [error]
    assert source.lookups == 1
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
