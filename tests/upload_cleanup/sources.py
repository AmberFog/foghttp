import asyncio
import threading

from .constants import CALLBACK_WATCHDOG


class SyncCloseGate:
    def __init__(self, *, blocked: bool = True, error: BaseException | None = None) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.calls = 0
        self.thread_id: int | None = None
        self.error = error
        if not blocked:
            self.release.set()

    def close(self) -> None:
        self.calls += 1
        self.thread_id = threading.get_ident()
        self.entered.set()
        try:
            if not self.release.wait(CALLBACK_WATCHDOG):
                message = "sync cleanup gate watchdog expired"
                raise RuntimeError(message)
        finally:
            self.finished.set()
        if self.error is not None:
            raise self.error


class AsyncCloseGate:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.finished = asyncio.Event()
        self.calls = 0

    async def aclose(self) -> None:
        self.calls += 1
        self.entered.set()
        try:
            await asyncio.wait_for(self.release.wait(), CALLBACK_WATCHDOG)
        finally:
            self.finished.set()
