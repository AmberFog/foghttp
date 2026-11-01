import asyncio
from concurrent.futures import Future
import threading

from foghttp._upload_body.cleanup_owner import CleanupOwner

from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


async def wait_sync_event(event: threading.Event) -> bool:
    return await asyncio.to_thread(event.wait, COMPLETION_WATCHDOG)


async def wait_cleanup_count(owner: CleanupOwner, key: str, expected: int) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + COMPLETION_WATCHDOG
    while owner.snapshot()[key] != expected:
        if loop.time() >= deadline:
            message = f"cleanup {key} did not reach {expected}: {owner.snapshot()}"
            raise AssertionError(message)
        await asyncio.sleep(0)


def finish_sync_cleanups(sources: list[SyncCloseGate], completions: list[Future[None]]) -> None:
    for source in sources:
        source.release.set()
    for completion in completions:
        completion.result(timeout=COMPLETION_WATCHDOG)
