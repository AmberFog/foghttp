import asyncio

import pytest

from foghttp._upload_body import cleanup, cleanup_owner

from .constants import COMPLETION_WATCHDOG
from .sources import SyncCloseGate


class ClosedLoopNotification:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        self.calls += 1
        message = "Event loop is closed"
        raise RuntimeError(message)


class DeferredCleanupLoop:
    def __init__(self, owner: cleanup_owner.CleanupOwner) -> None:
        self.owner = owner
        self.loop = asyncio.new_event_loop()
        self.errors: list[dict[str, object]] = []
        self.loop.set_exception_handler(self._record_error)
        self.source = SyncCloseGate()
        self.cleanup = cleanup.UploadSourceCleanup(self.source, reservation=owner.reserve(1))
        self.waiter = self.loop.run_until_complete(self._start())
        if not self.source.entered.wait(COMPLETION_WATCHDOG):
            pytest.fail("cleanup callback did not start")

    async def _start(self) -> asyncio.Future[None]:
        future = self.cleanup.start_async_cleanup()
        if future is None:
            pytest.fail("cleanup did not create its loop-local waiter")
        return future

    def complete_callback(self) -> SyncCloseGate:
        self.source.release.set()
        self.cleanup.completion.result(timeout=COMPLETION_WATCHDOG)
        barrier = SyncCloseGate(blocked=False)
        completion = self.owner.reserve(1).submit_sync(barrier.close)
        completion.result(timeout=COMPLETION_WATCHDOG)
        return barrier

    def close(self) -> None:
        self.source.release.set()
        self.cleanup.completion.result(timeout=COMPLETION_WATCHDOG)
        if not self.loop.is_closed():
            self.waiter.cancel()
            self.loop.run_until_complete(self.cleanup.aclose(bounded=False))
            self.loop.close()

    def _record_error(self, _loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        self.errors.append(context)
