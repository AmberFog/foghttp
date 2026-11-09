import asyncio

from foghttp._upload_body import cleanup, cleanup_owner

from .cleanup_actions import wait_cleanup_count
from .constants import COMPLETION_WATCHDOG
from .sources import AsyncCloseGate
from .task_factories import cancel_before_first_step


async def test_async_callback_cancelled_before_first_step_retains_obligation_until_retry(
    isolated_cleanup_owner: cleanup_owner.CleanupOwner,
) -> None:
    source = AsyncCloseGate()
    source_cleanup = cleanup.UploadSourceCleanup(source, reservation=isolated_cleanup_owner.reserve(1))
    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(cancel_before_first_step)
    try:
        completion = source_cleanup.start_async_cleanup()
        assert completion is not None
        await wait_cleanup_count(isolated_cleanup_owner, "stalled", 1)

        assert source.calls == 0
        assert completion.done() is False
        assert isolated_cleanup_owner.snapshot()["reserved"] == 1
        assert isolated_cleanup_owner.snapshot()["active"] == 0
    finally:
        loop.set_task_factory(previous_factory)
        source.release.set()
        await asyncio.wait_for(source_cleanup.aclose(bounded=False), COMPLETION_WATCHDOG)

    assert source.calls == 1
    assert source.finished.is_set() is True
    assert isolated_cleanup_owner.snapshot()["reserved"] == 0
