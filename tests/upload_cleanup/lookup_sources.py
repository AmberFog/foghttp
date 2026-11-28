import threading

from .constants import COMPLETION_WATCHDOG


class ControlLookupSource:
    def __init__(self, error: BaseException, *, gated: bool = False) -> None:
        self.error = error
        self.lookups = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        if not gated:
            self.release.set()

    @property
    def aclose(self) -> object:
        self.lookups += 1
        self.entered.set()
        if not self.release.wait(COMPLETION_WATCHDOG):
            message = "close lookup gate timed out"
            raise RuntimeError(message)
        raise self.error
