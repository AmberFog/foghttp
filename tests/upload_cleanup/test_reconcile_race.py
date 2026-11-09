import asyncio

from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .reconcile_race import ReconcileRace
from .sources import AsyncCloseGate


async def test_reconciliation_keeps_a_stable_cancelled_task_during_concurrent_done_callback() -> None:
    owner = CleanupOwner(max_active=1, max_obligations=1)
    race = ReconcileRace(owner)
    source = AsyncCloseGate()
    source.release.set()

    loop = asyncio.get_running_loop()
    previous_factory = loop.get_task_factory()
    loop.set_task_factory(race.task_factory)
    completion = owner.reserve(1).submit_async(source.aclose)
    try:
        assert await asyncio.to_thread(race.finished.wait, COMPLETION_WATCHDOG)
    finally:
        race.resume_read.set()
        loop.set_task_factory(previous_factory)
        if race.thread is not None:
            await asyncio.to_thread(race.thread.join, COMPLETION_WATCHDOG)

    assert race.error is None
    assert race.observation is not None
    assert race.observation["reserved"] == 1
    assert race.observation["active"] == 0
    assert race.observation["stalled"] == 1
    assert source.calls == 0
    assert completion.done() is False

    owner.retry()
    await asyncio.wait_for(asyncio.wrap_future(completion), COMPLETION_WATCHDOG)

    assert source.calls == 1
    assert source.finished.is_set() is True
    assert owner.snapshot()["reserved"] == 0
